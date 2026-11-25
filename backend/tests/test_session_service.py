"""
Tests for backend.session_service.SessionService. No FastAPI, no
langgraph — exercises the real SessionService against FakeGraphRunner

"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.session_service import (  # noqa: E402
    SessionService, SessionNotFoundError, SessionAlreadyCompletedError, InvalidMessageError,
)
from backend.tests._fake_graph_runner import FakeGraphRunner  # noqa: E402


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="session_service_test_")
        self.runner = FakeGraphRunner(output_root=self.tmp)
        self.service = SessionService(self.runner)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_session_returns_first_question(self):
        record = self.service.create_session()
        self.assertEqual(record.status, "waiting_for_input")
        self.assertEqual(record.question, FakeGraphRunner.QUESTIONS[0])
        self.assertTrue(record.session_id)

    def test_get_session_returns_the_same_record(self):
        created = self.service.create_session()
        fetched = self.service.get_session(created.session_id)
        self.assertEqual(fetched.session_id, created.session_id)

    def test_get_unknown_session_raises(self):
        with self.assertRaises(SessionNotFoundError):
            self.service.get_session("does-not-exist")

    def test_full_conversation_reaches_completed_status(self):
        record = self.service.create_session()
        record = self.service.submit_message(record.session_id, "My Project")
        self.assertEqual(record.status, "waiting_for_input")
        record = self.service.submit_message(record.session_id, "It manages tasks.")
        self.assertEqual(record.status, "completed")
        self.assertIsNotNone(record.result)
        self.assertEqual(record.result["canonical_status"], "requires_human_review")

    def test_submitting_after_completion_raises(self):
        record = self.service.create_session()
        record = self.service.submit_message(record.session_id, "My Project")
        record = self.service.submit_message(record.session_id, "It manages tasks.")
        self.assertEqual(record.status, "completed")
        with self.assertRaises(SessionAlreadyCompletedError):
            self.service.submit_message(record.session_id, "one more message")

    def test_empty_message_raises_invalid_message_error(self):
        record = self.service.create_session()
        with self.assertRaises(InvalidMessageError):
            self.service.submit_message(record.session_id, "   ")

    def test_non_string_message_raises_invalid_message_error(self):
        record = self.service.create_session()
        with self.assertRaises(InvalidMessageError):
            self.service.submit_message(record.session_id, 12345)

    def test_submitting_to_unknown_session_raises_session_not_found(self):
        with self.assertRaises(SessionNotFoundError):
            self.service.submit_message("bogus-id", "hello")


class SessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="session_isolation_test_")
        self.runner = FakeGraphRunner(output_root=self.tmp)
        self.service = SessionService(self.runner)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_sessions_get_distinct_ids_and_independent_state(self):
        a = self.service.create_session()
        b = self.service.create_session()
        self.assertNotEqual(a.session_id, b.session_id)

        a = self.service.submit_message(a.session_id, "Project A")
        # B is untouched by A's progress.
        b_fetched = self.service.get_session(b.session_id)
        self.assertEqual(b_fetched.question, FakeGraphRunner.QUESTIONS[0])

    def test_two_sessions_get_distinct_run_ids_and_output_dirs(self):
        a = self.service.create_session()
        b = self.service.create_session()
        self.assertNotEqual(a.run_id, b.run_id)
        self.assertNotEqual(a.output_dir, b.output_dir)


class RunIdThreadIdStabilityTests(unittest.TestCase):
    """
    Confirms run_id/output_dir are set once and carried through every
    subsequent record for the same session — "do not create a fresh
    session or artifact directory for every message."
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="run_id_stability_test_")
        self.runner = FakeGraphRunner(output_root=self.tmp)
        self.service = SessionService(self.runner)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_id_and_output_dir_stay_constant_across_messages(self):
        record = self.service.create_session()
        first_run_id = record.run_id
        first_output_dir = record.output_dir

        record = self.service.submit_message(record.session_id, "My Project")
        self.assertEqual(record.run_id, first_run_id)
        self.assertEqual(record.output_dir, first_output_dir)

        record = self.service.submit_message(record.session_id, "Description")
        self.assertEqual(record.run_id, first_run_id)
        self.assertEqual(record.output_dir, first_output_dir)


class PublicDictOmitsInternalPathsTests(unittest.TestCase):
    def test_to_public_dict_never_includes_output_dir_or_run_id(self):
        tmp = tempfile.mkdtemp(prefix="public_dict_test_")
        try:
            runner = FakeGraphRunner(output_root=tmp)
            service = SessionService(runner)
            record = service.create_session()
            public = record.to_public_dict()
            self.assertNotIn("output_dir", public)
            self.assertNotIn("run_id", public)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
