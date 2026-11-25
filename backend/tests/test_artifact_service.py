"""
Tests for backend.artifact_service.ArtifactService, including the
security-critical cases: session isolation and rejection of any
attempt to access a file outside a session's own registered directory.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.artifact_service import ArtifactService, ArtifactNotFoundError, _artifact_id_for  # noqa: E402


class ArtifactListingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="artifact_service_test_")
        self.service = ArtifactService()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content="x"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_unregistered_session_lists_no_artifacts(self):
        self.assertEqual(self.service.list_artifacts("never-registered"), [])

    def test_registered_session_with_no_files_yet_lists_empty(self):
        self.service.register_run("s1", self.tmp)
        self.assertEqual(self.service.list_artifacts("s1"), [])

    def test_listing_reflects_actual_files_with_content_types(self):
        self._write("requirements.json")
        self._write("project_requirements.docx")
        self._write("logo.svg")
        self.service.register_run("s1", self.tmp)
        artifacts = self.service.list_artifacts("s1")
        self.assertEqual(len(artifacts), 3)
        by_name = {a["filename"]: a for a in artifacts}
        self.assertEqual(by_name["requirements.json"]["content_type"], "application/json")
        self.assertEqual(by_name["logo.svg"]["content_type"], "image/svg+xml")
        self.assertEqual(
            by_name["project_requirements.docx"]["content_type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_artifact_ids_are_stable_across_repeated_listings(self):
        self._write("requirements.json")
        self.service.register_run("s1", self.tmp)
        first = self.service.list_artifacts("s1")[0]["artifact_id"]
        second = self.service.list_artifacts("s1")[0]["artifact_id"]
        self.assertEqual(first, second)
        self.assertEqual(first, _artifact_id_for("requirements.json"))


class ArtifactAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp_a = tempfile.mkdtemp(prefix="artifact_session_a_")
        self.tmp_b = tempfile.mkdtemp(prefix="artifact_session_b_")
        self.service = ArtifactService()

    def tearDown(self):
        shutil.rmtree(self.tmp_a, ignore_errors=True)
        shutil.rmtree(self.tmp_b, ignore_errors=True)

    def _write(self, directory, name, content="x"):
        path = os.path.join(directory, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_get_artifact_path_returns_correct_file_for_owning_session(self):
        self._write(self.tmp_a, "requirements.json", content="session A content")
        self.service.register_run("session-a", self.tmp_a)
        artifact_id = _artifact_id_for("requirements.json")
        resolved = self.service.get_artifact_path("session-a", artifact_id)
        with open(resolved) as f:
            self.assertEqual(f.read(), "session A content")

    def test_session_cannot_access_another_sessions_artifact_even_with_same_filename(self):
        self._write(self.tmp_a, "requirements.json", content="A")
        self._write(self.tmp_b, "requirements.json", content="B")
        self.service.register_run("session-a", self.tmp_a)
        self.service.register_run("session-b", self.tmp_b)

        artifact_id = _artifact_id_for("requirements.json")  # same filename -> same id in both dirs
        resolved_a = self.service.get_artifact_path("session-a", artifact_id)
        resolved_b = self.service.get_artifact_path("session-b", artifact_id)
        # Each session's lookup must resolve to ITS OWN directory's file,
        # never the other session's, even though the artifact_id (a hash
        # of the filename alone) is identical for both.
        self.assertTrue(resolved_a.startswith(os.path.realpath(self.tmp_a)))
        self.assertTrue(resolved_b.startswith(os.path.realpath(self.tmp_b)))
        with open(resolved_a) as f:
            self.assertEqual(f.read(), "A")
        with open(resolved_b) as f:
            self.assertEqual(f.read(), "B")

    def test_artifact_id_belonging_only_to_session_b_is_not_found_under_session_a(self):
        self._write(self.tmp_b, "only_in_b.json")
        self.service.register_run("session-a", self.tmp_a)
        self.service.register_run("session-b", self.tmp_b)

        artifact_id = _artifact_id_for("only_in_b.json")
        with self.assertRaises(ArtifactNotFoundError):
            self.service.get_artifact_path("session-a", artifact_id)
        # But it IS found under its real owner.
        resolved = self.service.get_artifact_path("session-b", artifact_id)
        self.assertTrue(os.path.exists(resolved))

    def test_unregistered_session_raises_not_found(self):
        with self.assertRaises(ArtifactNotFoundError):
            self.service.get_artifact_path("never-registered", "whatever")

    def test_nonexistent_artifact_id_raises_not_found(self):
        self.service.register_run("session-a", self.tmp_a)
        with self.assertRaises(ArtifactNotFoundError):
            self.service.get_artifact_path("session-a", "0000deadbeef")


class PathTraversalRejectionTests(unittest.TestCase):
    """
    The service never accepts a client-supplied path or filename at
    all — artifact_id is opaque and only ever compared against hashes
    computed server-side from the session's own directory listing.
    These tests confirm that feeding it path-traversal-shaped strings
    as the artifact_id behaves exactly like any other unknown id:
    ArtifactNotFoundError, never a path escape.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="path_traversal_test_")
        self.service = ArtifactService()
        with open(os.path.join(self.tmp, "requirements.json"), "w") as f:
            f.write("legit content")
        self.service.register_run("s1", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_traversal_strings_as_artifact_id_are_rejected(self):
        dangerous_ids = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/passwd",
            "requirements.json",  # the literal filename, not its hash — also rejected
            "",
            "....//....//etc/passwd",
        ]
        for bad_id in dangerous_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ArtifactNotFoundError):
                    self.service.get_artifact_path("s1", bad_id)

    def test_only_the_correct_hash_resolves_anything(self):
        correct_id = _artifact_id_for("requirements.json")
        resolved = self.service.get_artifact_path("s1", correct_id)
        self.assertTrue(os.path.exists(resolved))


if __name__ == "__main__":
    unittest.main()
