"""Tests for services.triage_service (rule-based ambiguity / consistency triage)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

from services.triage_service import analyze, findings_to_concerns  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "requirements_real_sample.json")


def _ids(findings, category=None, severity=None):
    return [f for f in findings
            if (category is None or f["category"] == category) and (severity is None or f["severity"] == severity)]


class VagueWordingTests(unittest.TestCase):
    def test_vague_nfr_wording_is_flagged_with_the_exact_terms(self):
        findings = analyze({"non_functional_requirements": ["The platform should be user-friendly and intuitive."]})
        hits = _ids(findings, "vague_wording")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["target_ids"], ["NFR-001"])
        self.assertIn("user-friendly", hits[0]["term"])
        self.assertIn("intuitive", hits[0]["term"])
        self.assertEqual(hits[0]["severity"], "warning")

    def test_measurable_nfr_is_not_flagged(self):
        findings = analyze({"non_functional_requirements": ["95% of pages load within 3 seconds at 200 concurrent users."]})
        self.assertEqual(findings, [])

    def test_nfr_without_number_and_without_vague_terms_gets_info_only(self):
        findings = analyze({"non_functional_requirements": ["Data must be encrypted in transit."]})
        self.assertEqual([f["category"] for f in findings], ["unmeasurable"])
        self.assertEqual(findings[0]["severity"], "info")

    def test_vague_functional_requirement_flagged(self):
        findings = analyze({"functional_requirements": [
            {"id": "FR-1", "text": "The system shall respond quickly and handle reports, etc."}]})
        self.assertEqual(len(_ids(findings, "vague_wording")), 1)
        self.assertEqual(_ids(findings, "vague_wording")[0]["target_ids"], ["FR-1"])

    def test_user_story_and_criterion_wording_flagged(self):
        findings = analyze(
            {}, [{"id": "US-1", "i_want": "an easy export", "so_that": "I save time"}],
            [{"story_id": "US-1", "given": "a report", "when": "I export", "then": "it downloads quickly"}])
        kinds = sorted(f["target_kind"] for f in _ids(findings, "vague_wording"))
        self.assertEqual(kinds, ["acceptance_criterion", "user_story"])


class DuplicateAndScopeTests(unittest.TestCase):
    def test_near_identical_requirements_are_flagged_as_duplicates(self):
        findings = analyze({"functional_requirements": [
            {"id": "FR-1", "text": "The system shall export reports to PDF format"},
            {"id": "FR-2", "text": "The system shall export reports to PDF format."}]})
        dup = _ids(findings, "duplicate")
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0]["target_ids"], ["FR-1", "FR-2"])

    def test_different_requirements_are_not_duplicates(self):
        findings = analyze({"functional_requirements": [
            {"id": "FR-1", "text": "The system shall export reports to PDF format"},
            {"id": "FR-2", "text": "The system shall send scheduled email alerts to subscribers"}]})
        self.assertEqual(_ids(findings, "duplicate"), [])

    def test_item_in_scope_and_out_of_scope_is_a_potential_contradiction(self):
        findings = analyze({"scope": {"in": ["Payment services integration"], "out": ["Integration with payment services"]}})
        hits = _ids(findings, "scope_conflict")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "potential_contradiction")

    def test_requirement_overlapping_out_of_scope_item_is_flagged(self):
        findings = analyze({
            "functional_requirements": [{"id": "FR-4", "text": "The system shall process payment services integration for orders"}],
            "scope": {"in": [], "out": ["Integration with payment services"]}})
        self.assertEqual([f["target_ids"] for f in _ids(findings, "scope_conflict")], [["FR-4"]])

    def test_unrelated_requirement_does_not_trigger_scope_conflict(self):
        findings = analyze({
            "functional_requirements": [{"id": "FR-8", "text": "Integration with third-party analytics tools and APIs"}],
            "scope": {"in": [], "out": ["Integration with payment services"]}})
        self.assertEqual(_ids(findings, "scope_conflict"), [])


class DeterminismAndShapeTests(unittest.TestCase):
    def test_same_input_gives_identical_output(self):
        with open(FIXTURE) as f:
            d = json.load(f)
        a = analyze(d["analysis"], d["user_stories"], d["acceptance_criteria"])
        b = analyze(d["analysis"], d["user_stories"], d["acceptance_criteria"])
        self.assertEqual(a, b)

    def test_ids_are_sequential_and_unique(self):
        findings = analyze({"non_functional_requirements": ["fast", "scalable", "secure"]})
        self.assertEqual([f["id"] for f in findings], ["TRI-001", "TRI-002", "TRI-003"])

    def test_empty_and_malformed_inputs_do_not_crash(self):
        self.assertEqual(analyze(None), [])
        self.assertEqual(analyze({}), [])
        analyze({"functional_requirements": ["not a dict", 5], "non_functional_requirements": [1, None],
                 "scope": "oops"}, ["x"], [3])

    def test_input_is_not_mutated(self):
        analysis = {"functional_requirements": [{"id": "FR-1", "text": "fast and easy"}]}
        snapshot = json.dumps(analysis, sort_keys=True)
        analyze(analysis)
        self.assertEqual(json.dumps(analysis, sort_keys=True), snapshot)


class ConcernConversionTests(unittest.TestCase):
    def test_only_warnings_become_concerns_and_ids_are_mapped_to_canonical(self):
        findings = analyze({
            "functional_requirements": [{"id": "FR-1", "text": "Fast export"}],
            "non_functional_requirements": ["Data must be encrypted in transit."]})  # info only
        concerns = findings_to_concerns(findings, {"FR-1": "FR-001"}, {}, [])
        self.assertTrue(concerns)
        for c in concerns:
            self.assertFalse(c["resolved"])
            self.assertIn(c["type"], ("ambiguity", "potential_contradiction"))
        self.assertIn(["FR-001"], [c["related_ids"] for c in concerns])
        self.assertNotIn("unmeasurable", [c["category"] for c in concerns])

    def test_acceptance_criterion_concern_maps_to_canonical_criterion_id(self):
        findings = analyze({}, [], [{"story_id": "US-1", "given": "a", "when": "b", "then": "it is quick"}])
        prov = [{"legacy_story_id": "US-1", "position_within_story": 1, "canonical_id": "AC-007"}]
        concerns = findings_to_concerns(findings, {}, {"US-1": "US-001"}, prov)
        self.assertEqual(concerns[0]["related_ids"], ["AC-007"])


if __name__ == "__main__":
    unittest.main()
