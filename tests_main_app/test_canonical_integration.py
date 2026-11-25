
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _stubs import install_stubs  # noqa: E402
install_stubs()

import agent.nodes as nodes  # noqa: E402  (real production source)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "requirements_real_sample.json")


def load_real_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class CanonicalValidateNodeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="canonical_integration_test_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_real_fixture_through_the_actual_node_writes_canonical_artifact_in_run_dir(self):
        state = {"output_dir": self._tmp, "legacy_contract": load_real_fixture()}
        result = nodes.canonical_validate(state)

        self.assertEqual(result["canonical_status"], "requires_human_review")
        self.assertEqual(result["canonical_gaps"], [])

        artifact_path = os.path.join(self._tmp, "canonical_requirements.json")
        self.assertTrue(os.path.exists(artifact_path))
        with open(artifact_path) as f:
            written = json.load(f)
        self.assertEqual(written["canonical_status"], "requires_human_review")
        self.assertIn("canonical_contract", written)
        self.assertIn("canonical_provenance", written)

    def test_canonical_artifact_lands_under_the_given_output_dir_only(self):
        state = {"output_dir": self._tmp, "legacy_contract": load_real_fixture()}
        nodes.canonical_validate(state)
        # Nothing written outside output_dir.
        self.assertEqual(os.listdir(self._tmp), ["canonical_requirements.json"])

    def test_two_runs_with_separate_output_dirs_never_collide(self):
        tmp_a = tempfile.mkdtemp(prefix="run_a_", dir=self._tmp)
        tmp_b = tempfile.mkdtemp(prefix="run_b_", dir=self._tmp)
        legacy = load_real_fixture()

        nodes.canonical_validate({"output_dir": tmp_a, "legacy_contract": legacy})
        nodes.canonical_validate({"output_dir": tmp_b, "legacy_contract": legacy})

        self.assertTrue(os.path.exists(os.path.join(tmp_a, "canonical_requirements.json")))
        self.assertTrue(os.path.exists(os.path.join(tmp_b, "canonical_requirements.json")))

    def test_mapping_error_is_handled_gracefully_not_a_crash(self):
        legacy = load_real_fixture()
        # Deep-copy-free targeted corruption: point a story at an FR id
        # that doesn't exist, forcing adapter.MappingError.
        legacy = json.loads(json.dumps(legacy))  # cheap deep copy via round-trip
        legacy["user_stories"][0]["fr_ids"] = ["FR-999-does-not-exist"]

        state = {"output_dir": self._tmp, "legacy_contract": legacy}
        result = nodes.canonical_validate(state)  # must not raise

        self.assertEqual(result["canonical_status"], "mapping_error")
        self.assertIn("FR-999-does-not-exist", result["canonical_error"])

        artifact_path = os.path.join(self._tmp, "canonical_requirements.json")
        self.assertTrue(os.path.exists(artifact_path))
        with open(artifact_path) as f:
            written = json.load(f)
        self.assertEqual(written["canonical_status"], "mapping_error")

    def test_canonical_validate_does_not_mutate_the_legacy_contract_in_state(self):
        legacy = load_real_fixture()
        import copy
        snapshot = copy.deepcopy(legacy)
        state = {"output_dir": self._tmp, "legacy_contract": legacy}
        nodes.canonical_validate(state)
        self.assertEqual(state["legacy_contract"], snapshot)


class WriteRequirementsJsonExposesLegacyContractTests(unittest.TestCase):
    """Confirms the one-line addition to write_requirements_json (Phase
    3B.3) without re-deriving its logic: call the real function and
    check the new 'legacy_contract' key is present and matches what
    was actually written to disk."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="write_json_test_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_legacy_contract_in_return_value_matches_the_file_on_disk(self):
        state = {
            "output_dir": self._tmp,
            "answers": {
                "name": "Acme", "description": "A demo app.", "type": "web",
                "users": "Owners", "features": "login", "must_have": "login",
                "integrations": "None", "tech": "None", "budget_deadline": "None",
            },
            "theme": {"name": "Ocean Blue", "primary": "#1E6FD9", "background": "#F5F9FF"},
            "logo": "<svg></svg>",
            "analysis": {
                "objectives": ["Grow revenue"], "stakeholders": ["Owner"],
                "functional_requirements": [{"id": "FR-1", "text": "Login", "feature": "login"}],
                "non_functional_requirements": ["Fast"],
                "scope": {"in": ["login"], "out": ["billing"]},
                "risks": ["Scope creep"], "data_entities": ["User"],
            },
            "stories": [{"id": "US-1", "as_a": "user", "i_want": "to log in", "so_that": "I reach my account",
                         "fr_ids": ["FR-1"], "priority": "Must"}],
            "criteria": [{"id": "AC-1", "story_id": "US-1", "given": "g", "when": "w", "then": "t"}],
            "leftover": "",
        }
        result = nodes.write_requirements_json(state)
        self.assertIn("legacy_contract", result)
        with open(result["files"][0]) as f:
            on_disk = json.load(f)
        self.assertEqual(result["legacy_contract"], on_disk)


if __name__ == "__main__":
    unittest.main()
