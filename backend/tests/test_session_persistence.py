"""
Session history, ownership and restart-survival tests (no FastAPI, no langgraph).
A "restart" is simulated by building brand-new Database/SessionStore/SessionService
objects on the same SQLite file, as a new server process would.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.artifact_service import ArtifactService  # noqa: E402
from backend.db import Database  # noqa: E402
from backend.session_service import SessionNotFoundError, SessionService  # noqa: E402
from backend.session_store import SessionStore  # noqa: E402
from backend.tests._fake_graph_runner import FakeGraphRunner  # noqa: E402


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="session_persist_")
        self.db_path = os.path.join(self.tmp, "app.sqlite")
        self.runner = FakeGraphRunner(output_root=os.path.join(self.tmp, "runs"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _boot(self):
        """A 'server start': fresh objects over the same files."""
        store = SessionStore(Database(self.db_path))
        return SessionService(self.runner, store=store), store

    def test_session_survives_a_restart_and_can_continue(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="u1")
        rec = service.submit_message(rec.session_id, "ATLAS BI", user_id="u1")
        self.assertEqual(rec.status, "waiting_for_input")

        service2, _ = self._boot()  # restart
        again = service2.get_session(rec.session_id, "u1")
        self.assertEqual(again.question, rec.question)
        self.assertEqual(again.title, "ATLAS BI")
        done = service2.submit_message(rec.session_id, "A platform", user_id="u1")
        self.assertEqual(done.status, "completed")

    def test_run_id_and_output_dir_are_unchanged_across_a_restart(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="u1")
        service2, _ = self._boot()
        again = service2.submit_message(rec.session_id, "Name", user_id="u1")
        self.assertEqual((again.run_id, again.output_dir), (rec.run_id, rec.output_dir))

    def test_history_lists_only_the_users_own_sessions_newest_first(self):
        service, _ = self._boot()
        a1 = service.create_session(user_id="alice")
        b1 = service.create_session(user_id="bob")
        a2 = service.create_session(user_id="alice")
        service.submit_message(a1.session_id, "Alpha", user_id="alice")  # touches a1 -> newest
        ids = [r.session_id for r in service.list_sessions("alice")]
        self.assertEqual(ids, [a1.session_id, a2.session_id])
        self.assertNotIn(b1.session_id, ids)
        self.assertEqual([r.session_id for r in service.list_sessions("bob")], [b1.session_id])
        self.assertEqual(service.list_sessions("nobody"), [])

    def test_user_cannot_read_or_continue_someone_elses_session(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="alice")
        with self.assertRaises(SessionNotFoundError):
            service.get_session(rec.session_id, "bob")
        with self.assertRaises(SessionNotFoundError):
            service.submit_message(rec.session_id, "hijack", user_id="bob")
        # and the real owner is unaffected
        self.assertEqual(service.get_session(rec.session_id, "alice").status, "waiting_for_input")

    def test_title_comes_from_first_answer_and_is_not_overwritten(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="u")
        rec = service.submit_message(rec.session_id, "  First answer  ", user_id="u")
        rec = service.submit_message(rec.session_id, "Second answer", user_id="u")
        self.assertEqual(rec.title, "First answer")

    def test_history_item_has_no_internal_paths(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="u")
        item = rec.to_history_item()
        self.assertEqual(set(item), {"session_id", "title", "status", "created_at", "updated_at"})
        self.assertNotIn("output_dir", rec.to_public_dict())
        self.assertNotIn("user_id", rec.to_public_dict())

    def test_update_result_fields_merges_and_persists(self):
        service, _ = self._boot()
        rec = service.create_session(user_id="u")
        service.submit_message(rec.session_id, "a", user_id="u")
        done = service.submit_message(rec.session_id, "b", user_id="u")
        service.update_result_fields(done.session_id, {"canonical_status": "passed"})
        service2, _ = self._boot()
        again = service2.get_session(done.session_id, "u")
        self.assertEqual(again.result["canonical_status"], "passed")
        self.assertIn("analysis", again.result)  # other fields kept

    def test_artifacts_remain_downloadable_after_restart_via_resolver(self):
        service, store = self._boot()
        rec = service.create_session(user_id="u")
        service.submit_message(rec.session_id, "Proj", user_id="u")
        service.submit_message(rec.session_id, "Desc", user_id="u")

        service2, store2 = self._boot()  # restart: the artifact service starts empty
        artifacts = ArtifactService(resolver=lambda sid: (store2.get(sid) or {}).get("output_dir"))
        listed = artifacts.list_artifacts(rec.session_id)
        self.assertTrue(any(a["filename"] == "requirements.json" for a in listed))
        path = artifacts.get_artifact_path(rec.session_id, listed[0]["artifact_id"])
        self.assertTrue(os.path.isfile(path))

    def test_database_file_is_created_inside_a_new_directory(self):
        nested = os.path.join(self.tmp, "a", "b", "app.sqlite")
        Database(nested)
        self.assertTrue(os.path.isfile(nested))


if __name__ == "__main__":
    unittest.main()
