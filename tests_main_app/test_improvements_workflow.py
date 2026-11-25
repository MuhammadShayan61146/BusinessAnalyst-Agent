"""
Tests for the workflow changes: structured confirmation summary without a file
path, logo previews, business case / tasks capture, triage at the review gate,
and triage concerns flowing into the canonical validation.

Real agent.nodes functions are called; only `interrupt` (needs real LangGraph)
and `ask_llm_json` (needs a live model) are replaced by controlled fakes.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _stubs import install_stubs  # noqa: E402
install_stubs()

import agent.nodes as nodes  # noqa: E402
from config.constants import QUESTIONS  # noqa: E402


def _answers(**overrides):
    a = {q["key"]: f"answer for {q['key']}" for q in QUESTIONS}
    a.update(overrides)
    return a


class CaptureInterrupt:
    """Fake langgraph interrupt(): records the payload, returns a canned reply."""
    def __init__(self, reply):
        self.reply, self.payload = reply, None

    def __call__(self, payload):
        self.payload = payload
        return self.reply


class QuestionSetTests(unittest.TestCase):
    def test_business_case_and_tasks_questions_exist_at_the_end(self):
        keys = [q["key"] for q in QUESTIONS]
        self.assertEqual(keys[:9], ["name", "description", "type", "users", "features",
                                    "must_have", "integrations", "tech", "budget_deadline"])
        self.assertEqual(keys[9:], ["business_case", "tasks"])
        self.assertTrue(all(q.get("optional") for q in QUESTIONS[9:]))


class ConfirmSummaryTests(unittest.TestCase):
    def _state(self, tmp):
        return {"answers": _answers(), "theme": {"name": "Ocean Blue", "primary": "#1E6FD9", "background": "#fff"},
                "logo": "<svg xmlns='http://www.w3.org/2000/svg'></svg>", "output_dir": tmp}

    def test_payload_has_structured_summary_and_no_file_path(self):
        tmp = tempfile.mkdtemp(prefix="C:\\Users\\secret_")
        fake = CaptureInterrupt("yes")
        try:
            with mock.patch.object(nodes, "interrupt", fake):
                nodes.confirm_summary(self._state(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        payload = fake.payload
        self.assertEqual(len(payload["summary"]["answers"]), len(QUESTIONS))
        self.assertEqual(payload["summary"]["theme"]["name"], "Ocean Blue")
        self.assertIn("<svg", payload["summary"]["logo_svg"])
        blob = json.dumps(payload)
        self.assertNotIn(tmp, blob)
        self.assertNotIn("secret_", blob)
        self.assertIn("Type yes", payload["question"])

    def test_missing_answers_show_not_specified_instead_of_crashing(self):
        state = self._state("x")
        state["answers"] = {"name": "Only name"}
        fake = CaptureInterrupt("yes")
        with mock.patch.object(nodes, "interrupt", fake):
            nodes.confirm_summary(state)
        answers = [r["answer"] for r in fake.payload["summary"]["answers"]]
        self.assertEqual(answers[0], "Only name")
        self.assertTrue(all(a == "Not specified" for a in answers[1:]))


class PickLogoTests(unittest.TestCase):
    def test_payload_has_previews_and_no_absolute_path(self):
        tmp = tempfile.mkdtemp(prefix="logo_test_")
        fake = CaptureInterrupt("2")
        try:
            state = {"output_dir": tmp, "logos": ["<svg id='a'/>", "<svg id='b'/>", "<svg id='c'/>"]}
            with mock.patch.object(nodes, "interrupt", fake):
                result = nodes.pick_logo(state)
            self.assertEqual(result["logo"], "<svg id='b'/>")
            self.assertTrue(os.path.exists(os.path.join(tmp, "logo.svg")))  # legacy artifact still written
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual([p["label"] for p in fake.payload["previews"]], ["Option 1", "Option 2", "Option 3"])
        self.assertNotIn(tmp, json.dumps(fake.payload))


class AnalysisBusinessCaseTests(unittest.TestCase):
    def _run(self, **answer_overrides):
        def fake_llm(prompt):
            return {"objectives": ["o"], "stakeholders": [], "functional_requirements": [],
                    "non_functional_requirements": [], "scope": {"in": [], "out": []},
                    "risks": [], "data_entities": []}
        retrieval = mock.Mock()
        retrieval.retrieve.return_value = []
        state = {"answers": _answers(**answer_overrides), "gaps": ""}
        with mock.patch.object(nodes, "ask_llm_json", fake_llm), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=retrieval):
            return nodes.analyse_requirements(state)["analysis"]

    def test_client_text_is_copied_verbatim_and_tasks_are_split(self):
        a = self._run(business_case="Cut reporting time by half.", tasks="Design, Build the API; Test, Launch.")
        self.assertEqual(a["business_case"], "Cut reporting time by half.")
        self.assertEqual(a["tasks"], ["Design", "Build the API", "Test", "Launch"])

    def test_skipped_answers_stay_empty_and_are_never_invented(self):
        a = self._run(business_case="Not specified", tasks="Not specified")
        self.assertEqual(a["business_case"], "")
        self.assertEqual(a["tasks"], [])

    def test_runs_that_never_asked_the_questions_also_stay_empty(self):
        answers = {k: "x" for k in ["name", "description", "type", "users", "features",
                                     "must_have", "integrations", "tech", "budget_deadline"]}
        retrieval = mock.Mock(); retrieval.retrieve.return_value = []
        with mock.patch.object(nodes, "ask_llm_json", lambda p: {"scope": {"in": [], "out": []}}), \
             mock.patch("services.retrieval_service.RetrievalService", return_value=retrieval):
            a = nodes.analyse_requirements({"answers": answers, "gaps": ""})["analysis"]
        self.assertEqual((a["business_case"], a["tasks"]), ("", []))


class ReviewTriageTests(unittest.TestCase):
    def test_review_payload_lists_triage_findings_before_approval(self):
        state = {
            "analysis": {"functional_requirements": [{"id": "FR-1", "text": "Fast and easy export"}],
                         "non_functional_requirements": ["Should be scalable"]},
            "stories": [{"id": "US-1", "priority": "Must", "as_a": "user", "i_want": "export", "so_that": "share"}],
            "criteria": [{"story_id": "US-1", "given": "g", "when": "w", "then": "t"}],
        }
        fake = CaptureInterrupt("approve")
        with mock.patch.object(nodes, "interrupt", fake):
            result = nodes.review_stories(state)
        self.assertEqual(result["review"], "approve")
        self.assertIn("need your attention", fake.payload["question"])
        self.assertTrue(any(f["severity"] == "warning" for f in fake.payload["triage"]))
        self.assertIn("Type approve", fake.payload["question"])

    def test_clean_requirements_show_no_triage_block(self):
        state = {
            "analysis": {"functional_requirements": [{"id": "FR-1", "text": "The system shall export a report as PDF"}],
                         "non_functional_requirements": ["95% of reports export within 5 seconds"]},
            "stories": [{"id": "US-1", "priority": "Must", "as_a": "user", "i_want": "export", "so_that": "share"}],
            "criteria": [{"story_id": "US-1", "given": "g", "when": "w", "then": "t"}],
        }
        fake = CaptureInterrupt("approve")
        with mock.patch.object(nodes, "interrupt", fake):
            nodes.review_stories(state)
        self.assertNotIn("Triage:", fake.payload["question"])


def _clean_legacy(**analysis_overrides):
    analysis = {
        "objectives": ["Reduce manual reporting"], "stakeholders": ["Analysts"],
        "functional_requirements": [{"id": "FR-1", "text": "The system shall export a report as PDF", "feature": "export"}],
        "non_functional_requirements": ["95% of exports finish within 5 seconds"],
        "scope": {"in": ["PDF export"], "out": ["Mobile application"]}, "risks": ["Late delivery"],
        "data_entities": ["Report"], "business_case": "Analysts spend two days a month on manual reports.",
        "tasks": ["Design the export", "Implement it", "Test it"],
    }
    analysis.update(analysis_overrides)
    return {
        "project": {"name": "P", "description": "D", "type": "web"}, "qa": [],
        "ui": {"theme": {}, "logo_svg": ""}, "analysis": analysis,
        "user_stories": [{"id": "US-1", "as_a": "analyst", "i_want": "to export a report", "so_that": "I can share it",
                          "fr_ids": ["FR-1"], "priority": "Must"}],
        "acceptance_criteria": [{"id": "AC-1", "story_id": "US-1", "given": "a report", "when": "I export",
                                 "then": "a PDF file is downloaded"}],
        "validation": {"passed": True, "remaining_gaps": ""},
    }


class CanonicalValidateWithTriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="canon_triage_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_run_with_business_case_and_tasks_can_reach_passed(self):
        result = nodes.canonical_validate({"output_dir": self.tmp, "legacy_contract": _clean_legacy()})
        self.assertEqual(result["canonical_status"], "passed")
        self.assertEqual(result["canonical_concerns"], [])
        with open(os.path.join(self.tmp, "canonical_requirements.json")) as f:
            report = json.load(f)
        self.assertEqual(report["canonical_contract"]["business_case"],
                         "Analysts spend two days a month on manual reports.")
        self.assertEqual(report["canonical_contract"]["tasks"], ["Design the export", "Implement it", "Test it"])

    def test_vague_wording_keeps_status_at_requires_human_review(self):
        legacy = _clean_legacy(non_functional_requirements=["The platform should be user-friendly and intuitive."])
        result = nodes.canonical_validate({"output_dir": self.tmp, "legacy_contract": legacy})
        self.assertEqual(result["canonical_status"], "requires_human_review")
        self.assertEqual(len(result["canonical_concerns"]), 1)
        self.assertEqual(result["canonical_concerns"][0]["related_ids"], ["NFR-001"])
        self.assertFalse(result["canonical_concerns"][0]["resolved"])

    def test_missing_business_case_stays_unresolved_not_invented(self):
        legacy = _clean_legacy(business_case="", tasks=[])
        result = nodes.canonical_validate({"output_dir": self.tmp, "legacy_contract": legacy})
        self.assertEqual(result["canonical_status"], "requires_human_review")
        with open(os.path.join(self.tmp, "canonical_requirements.json")) as f:
            contract = json.load(f)["canonical_contract"]
        self.assertEqual(contract["business_case"]["status"], "unresolved")
        self.assertEqual(contract["tasks"]["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
