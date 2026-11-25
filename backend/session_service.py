"""
SessionService.

Owns the mapping from a public session_id to the underlying LangGraph
thread_id (kept EQUAL, by design: one BA conversation is one graph
thread) and to that session's run_id/output_dir (which are NOT the
same concept as thread_id — they come from the graph's own state,
set once by intro(), and preserved across every resume()).

Sessions are now stored in a SessionStore (SQLite), so:
  * session history survives a server restart;
  * every session has an owner (user_id) and a user can only see, continue
    or list their OWN sessions. A session belonging to someone else is
    reported as "not found" (never "forbidden"), so ids cannot be probed.

This class has no FastAPI import and no knowledge of HTTP. It depends only on
the GraphRunner interface. `user_id=None` (used by older tests and by trusted
internal code) skips the ownership check.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from backend.db import Database
from backend.session_store import SessionStore


class SessionNotFoundError(Exception):
    pass


class SessionAlreadyCompletedError(Exception):
    pass


class InvalidMessageError(Exception):
    pass


@dataclass
class SessionRecord:
    session_id: str
    status: str  # "waiting_for_input" | "completed" | "error"
    question: str = None
    options: list = field(default_factory=list)
    result: dict = None
    error: str = None
    run_id: str = None
    output_dir: str = None
    user_id: str = None
    title: str = None
    summary: dict = None      # structured confirmation summary (web UI)
    previews: list = field(default_factory=list)   # logo previews (web UI)
    triage: list = field(default_factory=list)     # triage findings at review
    created_at: float = None
    updated_at: float = None

    def to_public_dict(self) -> dict:
        """What the API may return to a client. Never includes output_dir or
        run_id (internal filesystem details) or the owner's user_id."""
        return {
            "session_id": self.session_id, "status": self.status, "question": self.question,
            "options": self.options, "result": self.result, "error": self.error,
            "title": self.title, "summary": self.summary, "previews": self.previews,
            "triage": self.triage,
        }

    def to_history_item(self) -> dict:
        return {"session_id": self.session_id, "title": self.title or "(untitled session)",
                "status": self.status, "created_at": self.created_at, "updated_at": self.updated_at}


class SessionService:
    def __init__(self, graph_runner, store: SessionStore = None):
        self._graph_runner = graph_runner
        # Default: a private in-memory store (same behaviour as before for
        # callers that do not pass one).
        self._store = store or SessionStore(Database(":memory:"))
        # One lock per session: two answers submitted at the same moment for the
        # same conversation (e.g. a double click) are processed one after the other.
        self._locks: dict = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, session_id: str):
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    # -- helpers ------------------------------------------------------------------
    @staticmethod
    def _from_fields(fields: dict) -> SessionRecord:
        return SessionRecord(**fields)

    def _save(self, record: SessionRecord) -> SessionRecord:
        self._store.save(record.__dict__)
        saved = self._store.get(record.session_id)
        return self._from_fields(saved)

    def _to_record(self, session_id, step, prior: SessionRecord = None, user_id=None) -> SessionRecord:
        # run_id/output_dir are set once by the graph's intro() node and never
        # change for the lifetime of a session; carrying the prior values
        # forward is how "do not create a fresh artifact directory per message"
        # is guaranteed here.
        return SessionRecord(
            session_id=session_id, status=step.status, question=step.question,
            options=step.options or [], result=step.result, error=step.error,
            run_id=step.run_id or (prior.run_id if prior else None),
            output_dir=step.output_dir or (prior.output_dir if prior else None),
            user_id=prior.user_id if prior else user_id,
            title=prior.title if prior else None,
            summary=getattr(step, "summary", None), previews=getattr(step, "previews", None) or [],
            triage=getattr(step, "triage", None) or [],
            created_at=prior.created_at if prior else None,
        )

    # -- API ----------------------------------------------------------------------
    def create_session(self, user_id: str = None) -> SessionRecord:
        session_id = str(uuid.uuid4())
        # session_id doubles as the LangGraph thread_id.
        step = self._graph_runner.start(session_id)
        return self._save(self._to_record(session_id, step, user_id=user_id))

    def get_session(self, session_id: str, user_id: str = None) -> SessionRecord:
        fields = self._store.get(session_id)
        if fields is None or (user_id is not None and fields["user_id"] != user_id):
            raise SessionNotFoundError(session_id)
        return self._from_fields(fields)

    def submit_message(self, session_id: str, message: str, user_id: str = None) -> SessionRecord:
        with self._lock_for(session_id):
            return self._submit_message_locked(session_id, message, user_id)

    def _submit_message_locked(self, session_id: str, message: str, user_id: str = None) -> SessionRecord:
        record = self.get_session(session_id, user_id)
        if record.status == "completed":
            raise SessionAlreadyCompletedError(session_id)
        if not isinstance(message, str) or message.strip() == "":
            raise InvalidMessageError("message must be a non-empty string")

        step = self._graph_runner.resume(session_id, message)
        updated = self._to_record(session_id, step, prior=record)
        if updated.title is None:
            # The first answer to the first question is the project name.
            updated.title = message.strip()[:80]
        return self._save(updated)

    def list_sessions(self, user_id: str) -> list:
        return [self._from_fields(f) for f in self._store.list_for_user(user_id)]

    def output_dir_for(self, session_id: str):
        fields = self._store.get(session_id)
        return fields["output_dir"] if fields else None

    def update_result_fields(self, session_id: str, patch: dict) -> SessionRecord:
        """Merge `patch` into a completed session's stored result (used after a
        human resolves triage concerns and the status is recomputed)."""
        record = self.get_session(session_id)
        merged = dict(record.result or {})
        merged.update(patch)
        record.result = merged
        return self._save(record)
