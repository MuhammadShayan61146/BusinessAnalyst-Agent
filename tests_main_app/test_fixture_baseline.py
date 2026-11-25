
import json
import os
import re
import unittest

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "requirements_real_sample.json")


def load_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class TopLevelShapeTests(unittest.TestCase):
    def test_top_level_keys_and_types_match_write_requirements_json(self):
        d = load_fixture()
        expected_types = {
            "project": dict, "qa": list, "ui": dict, "analysis": dict,
            "user_stories": list, "acceptance_criteria": list, "validation": dict,
        }
        self.assertEqual(set(d.keys()), set(expected_types.keys()))
        for key, expected_type in expected_types.items():
            self.assertIsInstance(d[key], expected_type, f"'{key}' type mismatch")

    def test_no_schema_version_tasks_or_business_case_fields_exist(self):
        # Confirms, against the REAL fixture, the Phase 3A.1 finding that
        # these canonical-schema fields are not produced by the current
        # generator at all.
        d = load_fixture()
        self.assertNotIn("schema_version", d)
        self.assertNotIn("tasks", d)
        self.assertNotIn("business_case", d)
        self.assertNotIn("tasks", d["analysis"])
        self.assertNotIn("business_case", d["analysis"])


class LegacyRequiredFieldTests(unittest.TestCase):
    def test_project_fields(self):
        d = load_fixture()
        for key in ("name", "description", "type"):
            self.assertIn(key, d["project"])
            self.assertIsInstance(d["project"][key], str)

    def test_analysis_fields_present_and_typed(self):
        a = load_fixture()["analysis"]
        for key in ("objectives", "stakeholders", "non_functional_requirements", "risks", "data_entities"):
            self.assertIn(key, a)
            self.assertIsInstance(a[key], list)
            self.assertTrue(all(isinstance(x, str) for x in a[key]), f"{key} should be a list of strings")
        self.assertIsInstance(a["functional_requirements"], list)
        self.assertIsInstance(a["scope"], dict)
        self.assertIn("in", a["scope"])
        self.assertIn("out", a["scope"])

    def test_non_functional_requirements_are_plain_strings_not_objects(self):
        # Documents the real-data confirmation (Phase 3A.2 Decision 1
        # mismatch table): NFRs are flat strings in production output,
        # NOT {id, text} objects as the canonical schema expects.
        a = load_fixture()["analysis"]
        for nfr in a["non_functional_requirements"]:
            self.assertIsInstance(nfr, str)
            self.assertNotIsInstance(nfr, dict)

    def test_stakeholders_and_risks_are_present_and_non_empty(self):
        # Supports locked decision 3: these fields exist in real output
        # today and must be preserved going forward.
        a = load_fixture()["analysis"]
        self.assertGreater(len(a["stakeholders"]), 0)
        self.assertGreater(len(a["risks"]), 0)

    def test_ui_branding_fields_present(self):
        d = load_fixture()
        self.assertIn("theme", d["ui"])
        self.assertIn("logo_svg", d["ui"])
        theme = d["ui"]["theme"]
        for key in ("name", "primary", "background"):
            self.assertIn(key, theme)
        self.assertTrue(d["ui"]["logo_svg"].strip().startswith("<svg"))

    def test_validation_field_shape(self):
        v = load_fixture()["validation"]
        self.assertIn("passed", v)
        self.assertIn("remaining_gaps", v)
        self.assertIsInstance(v["passed"], bool)
        self.assertIsInstance(v["remaining_gaps"], str)


class IdFormatAndReferenceTests(unittest.TestCase):
    """
    'Where supported by the fixture' — this fixture DOES support
    uniqueness/reference checks for FR and US ids, so those are
    asserted as passing invariants. For AC ids, the fixture reveals a
    real defect (see DiscoveredDefectTests below) — that is
    documented, not silently asserted away.
    """

    def test_fr_and_us_ids_match_prefix_dash_digits_pattern(self):
        d = load_fixture()
        fr_ids = [fr["id"] for fr in d["analysis"]["functional_requirements"]]
        us_ids = [s["id"] for s in d["user_stories"]]
        self.assertTrue(all(re.fullmatch(r"FR-\d+", i) for i in fr_ids))
        self.assertTrue(all(re.fullmatch(r"US-\d+", i) for i in us_ids))

    def test_fr_ids_are_globally_unique(self):
        d = load_fixture()
        fr_ids = [fr["id"] for fr in d["analysis"]["functional_requirements"]]
        self.assertEqual(len(fr_ids), len(set(fr_ids)))

    def test_us_ids_are_globally_unique(self):
        d = load_fixture()
        us_ids = [s["id"] for s in d["user_stories"]]
        self.assertEqual(len(us_ids), len(set(us_ids)))

    def test_every_user_story_fr_reference_resolves_to_a_real_fr(self):
        d = load_fixture()
        fr_ids = {fr["id"] for fr in d["analysis"]["functional_requirements"]}
        for story in d["user_stories"]:
            for fr_id in story["fr_ids"]:
                self.assertIn(fr_id, fr_ids, f"{story['id']} references nonexistent {fr_id}")

    def test_every_fr_has_at_least_one_linked_story_in_this_sample(self):
        d = load_fixture()
        fr_ids = {fr["id"] for fr in d["analysis"]["functional_requirements"]}
        linked = set()
        for story in d["user_stories"]:
            linked.update(story["fr_ids"])
        self.assertEqual(fr_ids, linked, "orphan FR(s) found in this sample")


class DiscoveredDefectTests(unittest.TestCase):
    """
    These tests lock in CURRENTLY OBSERVED (defective) behavior as a
    regression baseline. They are not asserting this is correct — they
    exist so that if a later stage changes this behavior, it is a
    deliberate, visible change, not an accidental one. See baseline
    report Section 5 for the full writeup.
    """

    def test_known_defect_acceptance_criteria_ids_are_not_globally_unique(self):
        d = load_fixture()
        ac_ids = [c["id"] for c in d["acceptance_criteria"]]
        # Documented fact about THIS fixture: AC ids repeat AC-1..AC-4
        # once per story, because generate_acceptance_criteria's
        # prompt asks the model to number "2 to 4 acceptance criteria"
        # per story without instructing globally-unique numbering
        # across the whole batch.
        self.assertGreater(len(ac_ids), len(set(ac_ids)),
                            "if this now passes, the known AC-id defect may have been fixed upstream — "
                            "update this test's framing, don't just delete it")
        self.assertTrue(all(re.fullmatch(r"AC-\d+", i) for i in ac_ids))

    def test_known_defect_ac_story_id_pairs_are_unique_even_though_ac_id_alone_is_not(self):
        # The data is NOT corrupted — (id, story_id) pairs are unique,
        # it's only the bare 'id' field that collides across stories.
        # This matters directly for Decision 1's ID-mapping design.
        d = load_fixture()
        pairs = [(c["id"], c["story_id"]) for c in d["acceptance_criteria"]]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_every_acceptance_criterion_story_id_resolves_to_a_real_story(self):
        d = load_fixture()
        us_ids = {s["id"] for s in d["user_stories"]}
        for c in d["acceptance_criteria"]:
            self.assertIn(c["story_id"], us_ids)


if __name__ == "__main__":
    unittest.main()
