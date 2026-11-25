"""
 It simulates a short, fixed Q&A sequence
ending in a "completed" status with a canned analysis/validation
result, which is enough to exercise SessionService's and the API
layer's own session/thread/run/artifact logic end-to-end — all of
which is real, unmodified production code. It says nothing about the
real BA Agent's actual question flow, LLM behavior, or RAG quality.
"""
import os
import tempfile

from backend.graph_runner import GraphRunner, StepResult


class FakeGraphRunner(GraphRunner):
    QUESTIONS = ["What is your project called?", "What does it do?"]

    def __init__(self, output_root=None):
        self._output_root = output_root or tempfile.mkdtemp(prefix="fake_graph_runner_")
        self._threads = {}  # thread_id -> {"step": int, "answers": [...]}

    def _run_dir_for(self, thread_id: str) -> str:
        path = os.path.join(self._output_root, f"run_{thread_id}")
        os.makedirs(path, exist_ok=True)
        return path

    def start(self, thread_id: str) -> StepResult:
        self._threads[thread_id] = {"step": 0, "answers": []}
        output_dir = self._run_dir_for(thread_id)
        return StepResult(
            status="waiting_for_input",
            question=self.QUESTIONS[0],
            options=[],
            run_id=f"fake-run-{thread_id}",
            output_dir=output_dir,
        )

    def resume(self, thread_id: str, reply: str) -> StepResult:
        if thread_id not in self._threads:
            return StepResult(status="error", error="unknown thread")
        state = self._threads[thread_id]
        state["answers"].append(reply)
        state["step"] += 1
        output_dir = self._run_dir_for(thread_id)

        if state["step"] < len(self.QUESTIONS):
            return StepResult(
                status="waiting_for_input",
                question=self.QUESTIONS[state["step"]],
                options=[],
                run_id=f"fake-run-{thread_id}",
                output_dir=output_dir,
            )

        # Simulate the real graph's completed-run artifacts and result shape.
        requirements_path = os.path.join(output_dir, "requirements.json")
        if not os.path.exists(requirements_path):
            with open(requirements_path, "w") as f:
                f.write('{"project": {"name": "%s"}}' % state["answers"][0])

        return StepResult(
            status="completed",
            result={
                "analysis": {
                    "objectives": ["Demonstrate the BA workflow end-to-end"],
                    "functional_requirements": [{"id": "FR-1", "text": state["answers"][1], "feature": "core"}],
                },
                "stories": [],
                "criteria": [],
                "retrieved_evidence": [],
                "canonical_status": "requires_human_review",
                "canonical_gaps": [],
            },
            run_id=f"fake-run-{thread_id}",
            output_dir=output_dir,
        )
