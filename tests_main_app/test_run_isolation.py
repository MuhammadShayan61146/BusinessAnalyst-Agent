
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

from _stubs import install_stubs  # noqa: E402
install_stubs()

import config.settings as settings  # noqa: E402  (real production source, unmodified)
import agent.nodes as nodes  # noqa: E402


class TempOutputDirMixin:
    """Redirects RUNS_DIR to a temp dir for the duration of each test,
    so nothing here ever touches the real outputs/ tree."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ba_run_isolation_test_")
        self._patcher = mock.patch.object(settings, "RUNS_DIR", os.path.join(self._tmp, "runs"))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)


class RunIdGenerationTests(TempOutputDirMixin, unittest.TestCase):
    def test_two_calls_produce_distinct_run_ids(self):
        a = settings.new_run_id("My Project")
        b = settings.new_run_id("My Project")
        self.assertNotEqual(a, b)

    def test_identical_project_name_never_collides_across_many_runs(self):
        ids = {settings.new_run_id("Same Name") for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_run_id_is_filesystem_safe_for_unusual_project_names(self):
        dangerous_names = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "con",  # reserved on Windows, should still just become a safe slug
            "a/b\\c:d*e?f\"g<h>i|j",
            "",
            "   ",
            "🚀 emoji project 🚀",
            "a" * 500,  # very long
            "DROP TABLE projects;--",
        ]
        for name in dangerous_names:
            with self.subTest(name=repr(name)):
                run_id = settings.new_run_id(name)
                # Must be a plain safe token: no separators, no "..", no
                # control chars, reasonable length.
                self.assertRegex(run_id, r"^[A-Za-z0-9_-]+$")
                self.assertNotIn("..", run_id)
                self.assertNotIn("/", run_id)
                self.assertNotIn("\\", run_id)
                self.assertLess(len(run_id), 200)

    def test_run_id_from_untrusted_name_still_creates_dir_inside_runs_dir_only(self):
        run_id = settings.new_run_id("../../../etc")
        path = settings.make_run_output_dir(run_id)
        # Resolved path must stay a direct child of RUNS_DIR — no escape.
        self.assertEqual(os.path.dirname(os.path.abspath(path)), os.path.abspath(settings.RUNS_DIR))
        self.assertTrue(os.path.isdir(path))


class MakeRunOutputDirTests(TempOutputDirMixin, unittest.TestCase):
    def test_two_different_runs_get_distinct_directories(self):
        id_a = settings.new_run_id("Project One")
        id_b = settings.new_run_id("Project One")  # SAME project name
        dir_a = settings.make_run_output_dir(id_a)
        dir_b = settings.make_run_output_dir(id_b)
        self.assertNotEqual(dir_a, dir_b)
        self.assertTrue(os.path.isdir(dir_a))
        self.assertTrue(os.path.isdir(dir_b))

    def test_resuming_the_same_run_id_resolves_to_the_same_directory(self):
        run_id = settings.new_run_id("Resumable Project")
        first = settings.make_run_output_dir(run_id)
        second = settings.make_run_output_dir(run_id)  # simulates calling again on resume
        self.assertEqual(first, second)

    def test_rejects_an_unsafe_run_id_rather_than_silently_mangling_it(self):
        with self.assertRaises(ValueError):
            settings.make_run_output_dir("../../etc/passwd")

    def test_rejects_run_id_with_path_separator(self):
        with self.assertRaises(ValueError):
            settings.make_run_output_dir("some/thing")


class InternationalStateFlowTests(TempOutputDirMixin, unittest.TestCase):
    """Confirms agent.nodes.intro() wires run identity into state the
    way every downstream writer now expects, and that writers resolve
    paths through state, not a mutable global."""

    def test_intro_sets_run_id_and_output_dir_in_returned_state_update(self):
        result = nodes.intro({})
        self.assertIn("run_id", result)
        self.assertIn("output_dir", result)
        self.assertTrue(os.path.isdir(result["output_dir"]))
        self.assertIn(result["run_id"], result["output_dir"])

    def test_two_separate_intro_calls_never_collide(self):
        a = nodes.intro({})
        b = nodes.intro({})
        self.assertNotEqual(a["output_dir"], b["output_dir"])

    def _full_state(self, output_dir):
        return {
            "output_dir": output_dir,
            "answers": {
                "name": "Acme", "description": "A demo app.", "type": "web",
                "users": "Small business owners", "features": "login, checkout",
                "must_have": "login", "integrations": "Not specified",
                "tech": "Not specified", "budget_deadline": "Not specified",
            },
            "theme": {"name": "Ocean Blue", "primary": "#1E6FD9", "background": "#F5F9FF"},
            "logo": "<svg></svg>",
            "analysis": {
                "objectives": ["Grow revenue"],
                "stakeholders": ["Owner"],
                "functional_requirements": [{"id": "FR-1", "text": "Users can log in.", "feature": "login"}],
                "non_functional_requirements": ["Must be fast"],
                "scope": {"in": ["login"], "out": ["billing"]},
                "risks": ["Scope creep"],
                "data_entities": ["User"],
            },
            "stories": [{"id": "US-1", "as_a": "user", "i_want": "to log in", "so_that": "I reach my account",
                         "fr_ids": ["FR-1"], "priority": "Must"}],
            "criteria": [{"id": "AC-1", "story_id": "US-1", "given": "valid creds", "when": "I submit",
                          "then": "I am logged in"}],
            "leftover": "",
        }

    def test_write_requirements_json_writes_into_the_runs_output_dir_not_the_legacy_global(self):
        run_id = settings.new_run_id("Acme")
        output_dir = settings.make_run_output_dir(run_id)
        state = self._full_state(output_dir)
        result = nodes.write_requirements_json(state)
        written_path = result["files"][0]
        self.assertEqual(os.path.dirname(written_path), output_dir)
        self.assertTrue(os.path.exists(written_path))
        self.assertEqual(os.path.basename(written_path), "requirements.json")  # legacy filename preserved

    def test_two_runs_with_identical_project_name_do_not_overwrite_each_others_json(self):
        run_id_a = settings.new_run_id("Acme")
        run_id_b = settings.new_run_id("Acme")
        dir_a = settings.make_run_output_dir(run_id_a)
        dir_b = settings.make_run_output_dir(run_id_b)

        state_a = self._full_state(dir_a)
        state_a["answers"] = {**state_a["answers"], "description": "Version A"}
        state_b = self._full_state(dir_b)
        state_b["answers"] = {**state_b["answers"], "description": "Version B"}

        path_a = nodes.write_requirements_json(state_a)["files"][0]
        path_b = nodes.write_requirements_json(state_b)["files"][0]

        self.assertNotEqual(path_a, path_b)
        import json
        with open(path_a) as f:
            content_a = json.load(f)
        with open(path_b) as f:
            content_b = json.load(f)
        self.assertEqual(content_a["project"]["description"], "Version A")
        self.assertEqual(content_b["project"]["description"], "Version B")  # B did not clobber A

    def test_write_requirements_json_preserves_all_legacy_top_level_fields(self):
        run_id = settings.new_run_id("Acme")
        output_dir = settings.make_run_output_dir(run_id)
        state = self._full_state(output_dir)
        path = nodes.write_requirements_json(state)["files"][0]
        import json
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(
            set(data.keys()),
            {"project", "qa", "ui", "analysis", "user_stories", "acceptance_criteria", "validation"},
        )

    def test_docx_writers_resolve_through_state_output_dir(self):
        run_id = settings.new_run_id("Acme")
        output_dir = settings.make_run_output_dir(run_id)
        state = self._full_state(output_dir)

        analysis_path = nodes.write_analysis_doc(state)["files"][0]
        prd_path = nodes.write_prd(state)["files"][0]
        stories_path = nodes.write_stories_doc(state)["files"][0]

        for path, expected_name in (
            (analysis_path, "requirement_analysis.docx"),
            (prd_path, "project_requirements.docx"),
            (stories_path, "user_stories.docx"),
        ):
            self.assertEqual(os.path.dirname(path), output_dir)
            self.assertEqual(os.path.basename(path), expected_name)  # legacy filenames preserved
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
