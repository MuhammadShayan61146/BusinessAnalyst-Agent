"""
Tests for adapter.adapter.adapt(), run against the REAL captured legacy
fixture (tests_main_app/fixtures/requirements_real_sample.json) as the
primary integration fixture, plus targeted synthetic cases for error
paths the real fixture doesn't happen to exercise.

Run :
    python3 -m unittest discover -s adapter/tests -v
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapter.adapter import adapt, MappingError  # noqa: E402
from ba_contract_prototype import schema  # noqa: E402
from ba_contract_prototype.validator import validate  # noqa: E402

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "tests_main_app", "fixtures", "requirements_real_sample.json"
)


def load_real_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class PurityTests(unittest.TestCase):
    def test_adapt_does_not_mutate_its_input(self):
        legacy = load_real_fixture()
        snapshot = copy.deepcopy(legacy)
        adapt(legacy)
        self.assertEqual(legacy, snapshot)

    def test_adapt_returns_brand_new_nested_structures_not_aliases(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        # Mutate the output's passthrough structures; the input must be unaffected.
        result.contract["legacy_ui"]["theme"]["primary"] = "#000000"
        result.contract["legacy_stakeholders"].append("Someone New")
        self.assertNotEqual(legacy["ui"]["theme"]["primary"], "#000000")
        self.assertNotIn("Someone New", legacy["analysis"]["stakeholders"])


class IdMappingTests(unittest.TestCase):
    def test_fr_ids_become_canonical_and_unique(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        fr_ids = [fr["id"] for fr in result.contract["functional_requirements"]]
        self.assertTrue(all(schema.is_well_formed_id(i, "functional_requirements") for i in fr_ids))
        self.assertEqual(len(fr_ids), len(set(fr_ids)))

    def test_us_ids_become_canonical_and_unique(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        us_ids = [s["id"] for s in result.contract["user_stories"]]
        self.assertTrue(all(schema.is_well_formed_id(i, "user_stories") for i in us_ids))
        self.assertEqual(len(us_ids), len(set(us_ids)))

    def test_id_maps_are_reversible(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        for legacy_id, canonical_id in result.provenance["fr_id_map"].items():
            self.assertEqual(result.provenance["reverse_fr_id_map"][canonical_id], legacy_id)
        for legacy_id, canonical_id in result.provenance["us_id_map"].items():
            self.assertEqual(result.provenance["reverse_us_id_map"][canonical_id], legacy_id)


class AcceptanceCriteriaDedupTests(unittest.TestCase):
    """Addresses the confirmed Phase 3B.1 defect: 28 real criteria,
    only 4 distinct legacy 'AC-*' strings, reused once per story."""

    def test_repeated_legacy_ac_ids_become_globally_unique_canonical_ids(self):
        legacy = load_real_fixture()
        # Confirm the defect is actually present in the fixture we're testing against.
        legacy_ac_ids = [c["id"] for c in legacy["acceptance_criteria"]]
        self.assertGreater(len(legacy_ac_ids), len(set(legacy_ac_ids)),
                            "fixture no longer reproduces the known AC-id collision; update this test")

        result = adapt(legacy)
        canonical_ac_ids = [c["id"] for c in result.contract["acceptance_criteria"]]
        self.assertEqual(len(canonical_ac_ids), len(set(canonical_ac_ids)))
        self.assertTrue(all(schema.is_well_formed_id(i, "acceptance_criteria") for i in canonical_ac_ids))
        self.assertEqual(len(canonical_ac_ids), len(legacy["acceptance_criteria"]))  # 1:1, nothing dropped or merged

    def test_provenance_uniquely_identifies_every_criterion(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        keys = [
            (p["legacy_id"], p["legacy_story_id"], p["original_list_position"], p["position_within_story"])
            for p in result.provenance["acceptance_criteria"]
        ]
        self.assertEqual(len(keys), len(set(keys)))
        # original_list_position alone must already be unique and complete.
        positions = [p["original_list_position"] for p in result.provenance["acceptance_criteria"]]
        self.assertEqual(sorted(positions), list(range(len(legacy["acceptance_criteria"]))))

    def test_every_ac_story_reference_resolves(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        canonical_us_ids = {s["id"] for s in result.contract["user_stories"]}
        for crit in result.contract["acceptance_criteria"]:
            self.assertIn(crit["story_id"], canonical_us_ids)

    def test_every_us_fr_reference_resolves(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        canonical_fr_ids = {fr["id"] for fr in result.contract["functional_requirements"]}
        for story in result.contract["user_stories"]:
            for fr_id in story["fr_ids"]:
                self.assertIn(fr_id, canonical_fr_ids)


class NfrConversionTests(unittest.TestCase):
    def test_legacy_nfr_strings_become_canonical_objects(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        for nfr in result.contract["non_functional_requirements"]:
            self.assertIsInstance(nfr, dict)
            self.assertIn("id", nfr)
            self.assertIn("text", nfr)
            self.assertTrue(nfr["text"].strip())
        self.assertEqual(
            len(result.contract["non_functional_requirements"]),
            len(legacy["analysis"]["non_functional_requirements"]),
        )

    def test_nfr_text_content_preserved_verbatim(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        legacy_texts = legacy["analysis"]["non_functional_requirements"]
        canonical_texts = [n["text"] for n in result.contract["non_functional_requirements"]]
        self.assertEqual(legacy_texts, canonical_texts)


class PreservationTests(unittest.TestCase):
    """Task D: nothing silently discarded."""

    def test_stakeholders_risks_qa_ui_project_type_legacy_validation_all_preserved(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        c = result.contract
        self.assertEqual(c["legacy_stakeholders"], legacy["analysis"]["stakeholders"])
        self.assertEqual(c["legacy_risks"], legacy["analysis"]["risks"])
        self.assertEqual(c["legacy_qa"], legacy["qa"])
        self.assertEqual(c["legacy_ui"], legacy["ui"])
        self.assertEqual(c["legacy_project_type"], legacy["project"]["type"])
        self.assertEqual(c["legacy_validation"], legacy["validation"])
        self.assertEqual(c["legacy_scope_out"], legacy["analysis"]["scope"]["out"])

    def test_legacy_functional_requirements_raw_preserves_source_refs_if_present(self):
        # Phase 3C.1: confirms RAG citation metadata (an optional
        # "source_refs" key the generator may attach per FR) survives
        # into the canonical output via this passthrough, without the
        # canonical FR shape itself needing to carry it.
        legacy = load_real_fixture()
        legacy = json.loads(json.dumps(legacy))
        legacy["analysis"]["functional_requirements"][0]["source_refs"] = [
            {"source": "demo.md", "chunk_id": "demo.md::0::abc123"}
        ]
        result = adapt(legacy)
        raw = result.contract["legacy_functional_requirements_raw"]
        self.assertEqual(raw[0]["source_refs"], [{"source": "demo.md", "chunk_id": "demo.md::0::abc123"}])
        # And the canonical FR item itself is unaffected (extra key not required there).
        self.assertNotIn("source_refs", result.contract["functional_requirements"][0])


class MissingDataHonestyTests(unittest.TestCase):
    """Task C: never fabricate."""

    def test_tasks_and_business_case_are_explicit_unresolved_markers(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        self.assertTrue(schema.is_unresolved_marker(result.contract["tasks"]))
        self.assertTrue(schema.is_unresolved_marker(result.contract["business_case"]))

    def test_client_provided_business_case_and_tasks_are_used_verbatim(self):
        legacy = json.loads(json.dumps(load_real_fixture()))
        legacy["analysis"]["business_case"] = "  Reduce reporting cost.  "
        legacy["analysis"]["tasks"] = ["Design", "Build", "  ", 7]
        result = adapt(legacy)
        self.assertEqual(result.contract["business_case"], "Reduce reporting cost.")
        self.assertEqual(result.contract["tasks"], ["Design", "Build"])
        self.assertEqual(validate(result.contract).gaps, [])

    def test_empty_business_case_and_tasks_stay_unresolved(self):
        legacy = json.loads(json.dumps(load_real_fixture()))
        legacy["analysis"]["business_case"] = "   "
        legacy["analysis"]["tasks"] = []
        result = adapt(legacy)
        self.assertTrue(schema.is_unresolved_marker(result.contract["business_case"]))
        self.assertTrue(schema.is_unresolved_marker(result.contract["tasks"]))

    def test_schema_version_matches_canonical_schema(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        self.assertEqual(result.contract["schema_version"], schema.SCHEMA_VERSION)

    def test_data_models_carries_no_fabricated_attributes(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        for dm in result.contract["data_models"]:
            self.assertEqual(dm["attributes"], [])  # legacy gave us entity names only — no invented attributes
            self.assertEqual(dm["relationships"], [])
            self.assertIn(dm["entity"], legacy["analysis"]["data_entities"])


class ValidatorOwnershipTests(unittest.TestCase):
    """Task E: validation.state must come exclusively from validate(), never
    copied from legacy validation.passed."""

    def test_validator_result_is_requires_human_review_not_forced_pass(self):
        # The real fixture's legacy validation.passed is True, but the
        # canonical contract is missing tasks/business_case (by honest
        # design, see MissingDataHonestyTests) — so the CORRECT outcome
        # is requires_human_review, not an inherited "passed". This test
        # would fail if a future change started copying legacy.passed.
        legacy = load_real_fixture()
        self.assertTrue(legacy["validation"]["passed"])  # confirm the premise
        result = adapt(legacy)
        vr = validate(result.contract)
        self.assertEqual(vr.state, schema.REQUIRES_HUMAN_REVIEW)
        self.assertEqual(vr.gaps, [])  # zero structural gaps — only honest unresolved markers

    def test_adapted_real_fixture_has_no_structural_gaps(self):
        legacy = load_real_fixture()
        result = adapt(legacy)
        vr = validate(result.contract)
        self.assertEqual([g.type for g in vr.gaps], [])


class MappingErrorDiagnosticsTests(unittest.TestCase):
    """Task A: never silently resolve an ambiguous reference."""

    def _minimal_valid_legacy(self):
        return {
            "project": {"name": "P", "description": "D", "type": "T"},
            "qa": [],
            "ui": {"theme": {}, "logo_svg": ""},
            "analysis": {
                "objectives": ["obj"], "stakeholders": [], "risks": [],
                "functional_requirements": [{"id": "FR-1", "text": "t", "feature": "f"}],
                "non_functional_requirements": ["fast"],
                "scope": {"in": ["x"], "out": []},
                "data_entities": ["Thing"],
            },
            "user_stories": [{"id": "US-1", "as_a": "u", "i_want": "w", "so_that": "s", "fr_ids": ["FR-1"], "priority": "Must"}],
            "acceptance_criteria": [{"id": "AC-1", "story_id": "US-1", "given": "g", "when": "w", "then": "t"}],
            "validation": {"passed": True, "remaining_gaps": ""},
        }

    def test_story_referencing_unknown_fr_raises_mapping_error(self):
        legacy = self._minimal_valid_legacy()
        legacy["user_stories"][0]["fr_ids"] = ["FR-999"]
        with self.assertRaises(MappingError) as ctx:
            adapt(legacy)
        self.assertIn("FR-999", str(ctx.exception))

    def test_criterion_referencing_unknown_story_raises_mapping_error(self):
        legacy = self._minimal_valid_legacy()
        legacy["acceptance_criteria"][0]["story_id"] = "US-999"
        with self.assertRaises(MappingError) as ctx:
            adapt(legacy)
        self.assertIn("US-999", str(ctx.exception))

    def test_duplicate_legacy_fr_id_raises_mapping_error(self):
        legacy = self._minimal_valid_legacy()
        legacy["analysis"]["functional_requirements"].append(
            {"id": "FR-1", "text": "dup", "feature": "dup"}
        )
        with self.assertRaises(MappingError):
            adapt(legacy)

    def test_non_string_fr_ids_type_raises_mapping_error_not_crash(self):
        legacy = self._minimal_valid_legacy()
        legacy["user_stories"][0]["fr_ids"] = "FR-1"  # string instead of list
        with self.assertRaises(MappingError):
            adapt(legacy)

    def test_non_string_nfr_raises_mapping_error_rather_than_fabricating(self):
        legacy = self._minimal_valid_legacy()
        legacy["analysis"]["non_functional_requirements"] = [{"unexpected": "object"}]
        with self.assertRaises(MappingError):
            adapt(legacy)

    def test_minimal_valid_legacy_adapts_and_passes_cleanly(self):
        # Sanity check that the minimal fixture itself is a valid
        # baseline (no unresolved markers triggered) before the
        # negative tests above modify it — isolates adapter defects
        # from fixture-construction mistakes.
        legacy = self._minimal_valid_legacy()
        result = adapt(legacy)
        vr = validate(result.contract)
        # tasks/business_case are still unresolved by design -> requires_human_review, not passed
        self.assertEqual(vr.state, schema.REQUIRES_HUMAN_REVIEW)
        self.assertEqual(vr.gaps, [])


if __name__ == "__main__":
    unittest.main()
