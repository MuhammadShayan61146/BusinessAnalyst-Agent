"""
Workflow integration tests : exercises the REAL
agent.nodes.analyse_requirements node (not a reimplementation of its
logic) with:
  - a controlled fake ask_llm_json that records the prompt it received
    and returns a canned analysis, so we can assert retrieved evidence
    actually reached the prompt text;
  - services.retrieval_service.RetrievalService mocked to return real
    VectorStoreService.RetrievedChunk instances, so the node's own
    evidence-formatting and state-population logic runs for real.


"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _stubs import install_stubs  # noqa: E402
install_stubs()

import agent.nodes as nodes  # noqa: E402  (real production source)
from services.vector_store_service import RetrievedChunk  # noqa: E402


def _base_state():
    return {
        "answers": {
            "name": "Nails By M", "description": "An online storefront for nail products.",
            "type": "web", "users": "Small business customers",
            "features": "product catalog, checkout, order tracking",
            "must_have": "checkout", "integrations": "Not specified",
            "tech": "Not specified", "budget_deadline": "Not specified",
        },
        "gaps": "",
    }


class RetrievalReachesThePromptTests(unittest.TestCase):
    def test_retrieved_evidence_is_included_in_the_prompt_sent_to_the_model(self):
        captured_prompts = []

        def fake_ask_llm_json(prompt):
            captured_prompts.append(prompt)
            return {
                "objectives": ["Sell products online"], "stakeholders": ["Owner"],
                "functional_requirements": [{"id": "FR-1", "text": "Checkout", "feature": "checkout"}],
                "non_functional_requirements": ["Fast"], "scope": {"in": ["checkout"], "out": []},
                "risks": [], "data_entities": ["Order"],
            }

        fake_chunk = RetrievedChunk(
            text="Guest checkout reduces cart abandonment.",
            source="knowledge_base/sample_ecommerce_best_practices.md",
            chunk_id="sample::0::deadbeef",
            score=0.8,
            metadata={},
        )
        fake_retrieval_instance = mock.Mock()
        fake_retrieval_instance.retrieve.return_value = [fake_chunk]

        with mock.patch.object(nodes, "ask_llm_json", fake_ask_llm_json), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=fake_retrieval_instance):
            result = nodes.analyse_requirements(_base_state())

        self.assertEqual(len(captured_prompts), 1)
        self.assertIn("Guest checkout reduces cart abandonment.", captured_prompts[0])
        self.assertIn("sample_ecommerce_best_practices.md", captured_prompts[0])
        self.assertIn("sample::0::deadbeef", captured_prompts[0])

    def test_retrieved_evidence_is_recorded_in_returned_state(self):
        def fake_ask_llm_json(prompt):
            return {"objectives": [], "stakeholders": [], "functional_requirements": [],
                    "non_functional_requirements": [], "scope": {"in": [], "out": []},
                    "risks": [], "data_entities": []}

        fake_chunk = RetrievedChunk(text="t", source="s.md", chunk_id="c1", score=0.5, metadata={"k": "v"})
        fake_retrieval_instance = mock.Mock()
        fake_retrieval_instance.retrieve.return_value = [fake_chunk]

        with mock.patch.object(nodes, "ask_llm_json", fake_ask_llm_json), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=fake_retrieval_instance):
            result = nodes.analyse_requirements(_base_state())

        self.assertEqual(len(result["retrieved_evidence"]), 1)
        self.assertEqual(result["retrieved_evidence"][0]["source"], "s.md")
        self.assertEqual(result["retrieved_evidence"][0]["chunk_id"], "c1")
        self.assertEqual(result["retrieved_evidence"][0]["score"], 0.5)


class EmptyOrUnavailableRetrievalTests(unittest.TestCase):
    def test_empty_retrieval_result_is_represented_explicitly_not_fabricated(self):
        def fake_ask_llm_json(prompt):
            # Confirm the prompt is honest about empty evidence, not
            # padded with invented content.
            self.assertIn("no relevant knowledge-base evidence retrieved", prompt)
            return {"objectives": [], "stakeholders": [], "functional_requirements": [],
                    "non_functional_requirements": [], "scope": {"in": [], "out": []},
                    "risks": [], "data_entities": []}

        fake_retrieval_instance = mock.Mock()
        fake_retrieval_instance.retrieve.return_value = []

        with mock.patch.object(nodes, "ask_llm_json", fake_ask_llm_json), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=fake_retrieval_instance):
            result = nodes.analyse_requirements(_base_state())

        self.assertEqual(result["retrieved_evidence"], [])

    def test_retrieval_construction_failure_does_not_crash_the_node(self):
        """
        Simulates the realistic case where GEMINI_API_KEY isn't set, so
        constructing RetrievalService's underlying store raises. The node
        must continue (degrading to empty evidence), not propagate the
        exception and abort the whole BA elicitation over an
        unconfigured, optional enhancement.
        """
        def fake_ask_llm_json(prompt):
            return {"objectives": [], "stakeholders": [], "functional_requirements": [],
                    "non_functional_requirements": [], "scope": {"in": [], "out": []},
                    "risks": [], "data_entities": []}

        with mock.patch.object(nodes, "ask_llm_json", fake_ask_llm_json), \
             mock.patch("services.retrieval_service.RetrievalService",
                         side_effect=RuntimeError("GEMINI_API_KEY not set")):
            result = nodes.analyse_requirements(_base_state())  # must not raise

        self.assertEqual(result["retrieved_evidence"], [])
        self.assertIn("analysis", result)


class EvidenceVsAssumptionInstructionTests(unittest.TestCase):
    def test_prompt_explicitly_distinguishes_source_supported_from_assumptions(self):
        captured_prompts = []

        def fake_ask_llm_json(prompt):
            captured_prompts.append(prompt)
            return {"objectives": [], "stakeholders": [], "functional_requirements": [],
                    "non_functional_requirements": [], "scope": {"in": [], "out": []},
                    "risks": [], "data_entities": []}

        fake_retrieval_instance = mock.Mock()
        fake_retrieval_instance.retrieve.return_value = []

        with mock.patch.object(nodes, "ask_llm_json", fake_ask_llm_json), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=fake_retrieval_instance):
            nodes.analyse_requirements(_base_state())

        prompt = captured_prompts[0]
        self.assertIn("NOT proof that any specific client requirement is", prompt)
        self.assertIn("do NOT treat retrieved general guidance as confirmation", prompt)
        self.assertIn("source_refs", prompt)


if __name__ == "__main__":
    unittest.main()
