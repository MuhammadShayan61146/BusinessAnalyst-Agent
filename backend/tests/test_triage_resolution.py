"""
Tests for backend.triage_resolution.TriageResolutionService, run against the
canonical_requirements.json that the REAL agent.nodes.canonical_validate writes
and the REAL ba_contract_prototype validator.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
for p in (ROOT, os.path.join(ROOT, "Business-Analyst-Agent-main"), os.path.join(ROOT, "tests_main_app")):
    sys.path.insert(0, p)

from _stubs import install_stubs  # noqa: E402
install_stubs()

import agent.nodes as nodes  # noqa: E402
from backend.triage_resolution import (  # noqa: E402
    CANONICAL_FILENAME, TriageResolutionError, TriageResolutionService,
)
from ba_contract_prototype.validator import validate  # noqa: E402


def legacy(nfrs):
    return {
        "project": {"name": "P", "description": "D", "type": "web"}, "qa": [],
        "ui": {"theme": {}, "logo_svg": ""},
        "analysis": {
            "objectives": ["Reduce manual reporting"], "stakeholders": ["Analysts"],
            "functional_requirements": [{"id": "FR-1", "text": "The system shall export a report as PDF", "feature": "export"}],
            "non_functional_requirements": nfrs, "scope": {"in": ["PDF export"], "out": []},
            "risks": [], "data_entities": ["Report"], "business_case": "Manual reports cost two days a month.",
            "tasks": ["Design", "Build"],
        },
        "user_stories": [{"id": "US-1", "as_a": "analyst", "i_want": "to export", "so_that": "I can share",
                          "fr_ids": ["FR-1"], "priority": "Must"}],
        "acceptance_criteria": [{"id": "AC-1", "story_id": "US-1", "given": "a report", "when": "I export",
                                 "then": "a PDF is downloaded"}],
        "validation": {"passed": True, "remaining_gaps": ""},
    }


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="triage_res_")
        self.svc = TriageResolutionService(validate)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, nfrs):
        return nodes.canonical_validate({"output_dir": self.tmp, "legacy_contract": legacy(nfrs)})

    def _report(self):
        with open(os.path.join(self.tmp, CANONICAL_FILENAME)) as f:
            return json.load(f)

    def test_resolving_the_only_concern_lets_the_validator_pass_the_contract(self):
        before = self._run(["The platform should be user-friendly and intuitive."])
        self.assertEqual(before["canonical_status"], "requires_human_review")
        cid = before["canonical_concerns"][0]["id"]

        out = self.svc.resolve(self.tmp, [cid], "alice")
        self.assertEqual(out["canonical_status"], "passed")
        self.assertEqual(out["open_concerns"], 0)
        report = self._report()
        self.assertEqual(report["canonical_status"], "passed")
        concern = report["canonical_contract"]["human_flagged_concerns"][0]
        self.assertTrue(concern["resolved"])
        self.assertEqual(concern["resolved_by"], "alice")
        self.assertIn("resolved_at", concern)

    def test_partial_resolution_keeps_status_at_requires_human_review(self):
        before = self._run(["Should be scalable.", "Must be reliable."])
        self.assertEqual(len(before["canonical_concerns"]), 2)
        first = before["canonical_concerns"][0]["id"]
        out = self.svc.resolve(self.tmp, [first], "alice")
        self.assertEqual(out["canonical_status"], "requires_human_review")
        self.assertEqual(out["open_concerns"], 1)

    def test_all_resolves_every_concern(self):
        self._run(["Should be scalable.", "Must be reliable."])
        out = self.svc.resolve(self.tmp, "all", "alice")
        self.assertEqual((out["canonical_status"], out["open_concerns"]), ("passed", 0))

    def test_unknown_or_empty_ids_are_rejected_and_nothing_changes(self):
        self._run(["Should be scalable."])
        before = self._report()
        for bad in (["TRI-999"], [], None):
            with self.subTest(ids=bad):
                with self.assertRaises(TriageResolutionError):
                    self.svc.resolve(self.tmp, bad, "alice")
        self.assertEqual(self._report(), before)

    def test_status_is_computed_by_the_validator_not_by_the_caller(self):
        """Even if every concern is resolved, a contract that is otherwise
        unresolved (no business case) must NOT become 'passed'."""
        data = legacy(["Should be scalable."])
        data["analysis"]["business_case"] = ""
        nodes.canonical_validate({"output_dir": self.tmp, "legacy_contract": data})
        out = self.svc.resolve(self.tmp, "all", "alice")
        self.assertEqual(out["canonical_status"], "requires_human_review")

    def test_a_stub_validator_result_is_what_gets_written(self):
        from types import SimpleNamespace
        self._run(["Should be scalable."])
        fake = TriageResolutionService(lambda contract: SimpleNamespace(
            state="failed", gaps=[], unresolved_markers=[]))
        self.assertEqual(fake.resolve(self.tmp, "all", "bob")["canonical_status"], "failed")
        self.assertEqual(self._report()["canonical_status"], "failed")

    def test_missing_file_and_mapping_error_reports_are_handled(self):
        with self.assertRaises(TriageResolutionError):
            self.svc.resolve(self.tmp, ["TRI-001"], "alice")  # nothing written yet
        with open(os.path.join(self.tmp, CANONICAL_FILENAME), "w") as f:
            json.dump({"canonical_status": "mapping_error", "canonical_error": "x"}, f)
        with self.assertRaises(TriageResolutionError):
            self.svc.resolve(self.tmp, ["TRI-001"], "alice")

    def test_no_temp_files_are_left_behind(self):
        self._run(["Should be scalable."])
        self.svc.resolve(self.tmp, "all", "alice")
        self.assertEqual(sorted(os.listdir(self.tmp)), [CANONICAL_FILENAME])


if __name__ == "__main__":
    unittest.main()
