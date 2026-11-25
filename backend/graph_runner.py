"""
GraphRunner: the one seam between the HTTP layer and the
actual LangGraph-based Business Analyst Agent.

GraphRunner defines the interrupt/resume contract every caller in this
backend depends on. 

"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """
    The one shape every GraphRunner call returns, regardless of which
    underlying node the graph is currently paused at or has finished on.

    status: "waiting_for_input" | "completed" | "error"
    question / options: populated when status == "waiting_for_input"
      (mirrors the real graph's interrupt({"question": ..., "options": ...})
      payload shape, confirmed by reading agent/nodes.py).
    result: populated when status == "completed" — the assembled,
      user-facing view of the finished run (analysis, stories, criteria,
      canonical_status, canonical_gaps, retrieved_evidence, artifact
      file list). Never fabricated: built only from what the underlying
      graph state actually contains.
    error: populated when status == "error" — a short, safe message
      (never a raw stack trace or an internal file path).
    run_id / output_dir: this run's isolated directory (Phase 3B.2),
      surfaced so the caller (SessionService) can register artifacts
      against it. None until the graph has actually reached intro().
    """
    status: str
    question: str = None
    options: list = field(default_factory=list)
    result: dict = None
    error: str = None
    run_id: str = None
    output_dir: str = None
    # Optional extras carried by some interrupt payloads (see agent/nodes.py):
    summary: dict = None                         # structured confirmation summary
    previews: list = field(default_factory=list)  # logo previews [{label, svg}]
    triage: list = field(default_factory=list)    # triage findings at the review gate


class GraphRunner:
    """Interface every concrete runner implements."""

    def start(self, thread_id: str) -> StepResult:
        raise NotImplementedError

    def resume(self, thread_id: str, reply: str) -> StepResult:
        raise NotImplementedError


class RealGraphRunner(GraphRunner):
    """
    Production implementation. Imported and constructed lazily — see
    module docstring for why this can't run in this sandbox.
    """

    def __init__(self, persistence: str = "memory", checkpoint_db: str = None):
        """
        persistence: "memory" (conversations are lost on restart) or "sqlite"
        (conversations survive a restart; needs the `langgraph-checkpoint-sqlite`
        package and a `checkpoint_db` file path). If "sqlite" is requested and the
        package is missing, this raises a clear error - it never silently falls
        back to memory, because that would quietly lose the persistence you asked for.
        """
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        app_dir = os.path.join(app_root, "Business-Analyst-Agent-main")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        # Imported here, not at module load time, for the reason given in
        # the module docstring.
        from langgraph.types import Command
        from agent.graph import build_graph

        self._Command = Command
        checkpointer = None
        if persistence == "sqlite":
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver
            except ImportError as e:
                raise RuntimeError(
                    "SESSION_PERSISTENCE=sqlite needs the 'langgraph-checkpoint-sqlite' package "
                    "(pip install langgraph-checkpoint-sqlite), or set SESSION_PERSISTENCE=memory."
                ) from e
            os.makedirs(os.path.dirname(os.path.abspath(checkpoint_db)), exist_ok=True)
            conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
            checkpointer = SqliteSaver(conn)
        elif persistence != "memory":
            raise ValueError(f"Unknown persistence mode {persistence!r} (use 'memory' or 'sqlite').")
        self.persistence = persistence
        # build_graph() is called exactly ONCE and the compiled graph is reused
        # for every session (distinguished only by thread_id), because each call
        # would otherwise create a separate checkpoint store.
        self._graph = build_graph(checkpointer=checkpointer)

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

    def _interpret(self, raw_result) -> StepResult:
        if "__interrupt__" in raw_result:
            payload = raw_result["__interrupt__"][0].value
            return StepResult(
                status="waiting_for_input",
                question=payload.get("question", ""),
                options=payload.get("options", []),
                summary=payload.get("summary"),
                previews=payload.get("previews") or [],
                triage=payload.get("triage") or [],
            )
        # No interrupt pending: the graph ran to completion on this thread.
        return StepResult(
            status="completed",
            result=self._assemble_result(raw_result),
            run_id=raw_result.get("run_id"),
            output_dir=raw_result.get("output_dir"),
        )

    def _assemble_result(self, state: dict) -> dict:
        """Builds the user-facing completed-run view strictly from actual
        graph state — no placeholder or invented fields."""
        return {
            "analysis": state.get("analysis"),
            "stories": state.get("stories"),
            "criteria": state.get("criteria"),
            "theme": state.get("theme"),
            "logo": state.get("logo"),
            "retrieved_evidence": state.get("retrieved_evidence", []),
            "canonical_status": state.get("canonical_status"),
            "canonical_gaps": state.get("canonical_gaps", []),
            "canonical_error": state.get("canonical_error"),
            "canonical_concerns": state.get("canonical_concerns", []),
            "triage_findings": state.get("triage_findings", []),
            "business_case": (state.get("analysis") or {}).get("business_case"),
            "tasks": (state.get("analysis") or {}).get("tasks"),
        }

    def start(self, thread_id: str) -> StepResult:
        try:
            raw_result = self._graph.invoke({}, config=self._config(thread_id))
        except Exception:
            logger.exception("Workflow failed to start (thread %s)", thread_id)
            return StepResult(status="error", error="The workflow failed to start.")
        result = self._interpret(raw_result)
        # run_id/output_dir are set by intro() on the first step; surface
        # them even on a waiting_for_input result so the caller can
        # register the run immediately.
        snapshot = self._graph.get_state(self._config(thread_id))
        result.run_id = snapshot.values.get("run_id")
        result.output_dir = snapshot.values.get("output_dir")
        return result

    def resume(self, thread_id: str, reply: str) -> StepResult:
        try:
            raw_result = self._graph.invoke(
                self._Command(resume=reply), config=self._config(thread_id)
            )
        except Exception:
            logger.exception("Workflow failed to process a reply (thread %s)", thread_id)
            return StepResult(status="error", error="The workflow failed to process that reply.")
        result = self._interpret(raw_result)
        snapshot = self._graph.get_state(self._config(thread_id))
        result.run_id = snapshot.values.get("run_id")
        result.output_dir = snapshot.values.get("output_dir")
        return result
