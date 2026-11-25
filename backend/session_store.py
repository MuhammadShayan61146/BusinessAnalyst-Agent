"""
SessionStore: saves session records (including who owns them) in SQLite so
that session history survives a server restart and each user can list their
own past sessions.

Paired with a persistent LangGraph checkpointer (see graph_runner.py), a
conversation that was waiting for an answer can continue after a restart.
"""
from __future__ import annotations

import json
import time


class SessionStore:
    def __init__(self, db):
        self._db = db

    @staticmethod
    def _row_to_fields(row) -> dict:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        return {
            "session_id": row["session_id"], "user_id": row["user_id"], "title": row["title"],
            "status": row["status"], "question": row["question"],
            "options": json.loads(row["options_json"]) if row["options_json"] else [],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"], "run_id": row["run_id"], "output_dir": row["output_dir"],
            "summary": extra.get("summary"), "previews": extra.get("previews") or [],
            "triage": extra.get("triage") or [],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def save(self, fields: dict) -> None:
        """Insert or update one session record (given as a dict of fields)."""
        now = time.time()
        extra = {"summary": fields.get("summary"), "previews": fields.get("previews") or [],
                 "triage": fields.get("triage") or []}
        with self._db.connect() as conn:
            existing = conn.execute("SELECT created_at FROM sessions WHERE session_id = ?",
                                    (fields["session_id"],)).fetchone()
            created = existing["created_at"] if existing else fields.get("created_at") or now
            conn.execute(
                "INSERT OR REPLACE INTO sessions(session_id, user_id, title, status, question, options_json, "
                "result_json, extra_json, error, run_id, output_dir, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fields["session_id"], fields.get("user_id"), fields.get("title"), fields["status"],
                 fields.get("question"), json.dumps(fields.get("options") or []),
                 json.dumps(fields["result"]) if fields.get("result") is not None else None,
                 json.dumps(extra), fields.get("error"), fields.get("run_id"), fields.get("output_dir"),
                 created, now))

    def get(self, session_id: str):
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return self._row_to_fields(row) if row else None

    def list_for_user(self, user_id: str) -> list:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
                                (user_id,)).fetchall()
        return [self._row_to_fields(r) for r in rows]
