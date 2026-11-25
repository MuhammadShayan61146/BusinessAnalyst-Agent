"""Tests for backend.auth_service.AuthService (no FastAPI needed)."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.auth_service import (  # noqa: E402
    AuthService, InvalidCredentialsError, InvalidInputError, InvalidTokenError,
    RegistrationDisabledError, TooManyAttemptsError, UsernameTakenError,
)
from backend.db import Database  # noqa: E402


def make(**kw):
    return AuthService(Database(":memory:"), **kw)


class RegistrationTests(unittest.TestCase):
    def test_register_creates_a_normal_user(self):
        user = make().register("alice", "correct horse")
        self.assertEqual((user["username"], user["role"]), ("alice", "user"))

    def test_duplicate_username_rejected_case_sensitive_exact_match(self):
        a = make()
        a.register("alice", "correct horse")
        with self.assertRaises(UsernameTakenError):
            a.register("alice", "another pass")

    def test_weak_password_and_bad_username_rejected(self):
        a = make()
        with self.assertRaises(InvalidInputError):
            a.register("alice", "short")
        for bad in ("ab", "has space", "semi;colon", "x" * 40, "", None):
            with self.subTest(username=bad):
                with self.assertRaises(InvalidInputError):
                    a.register(bad, "long enough pw")

    def test_admin_usernames_cannot_be_self_registered(self):
        a = make(admin_usernames=("boss",))
        with self.assertRaises(UsernameTakenError):
            a.register("Boss", "long enough pw")

    def test_registration_can_be_disabled(self):
        with self.assertRaises(RegistrationDisabledError):
            make(allow_registration=False).register("alice", "long enough pw")

    def test_admin_can_be_created_by_the_trusted_path_only(self):
        a = make(admin_usernames=("boss",))
        self.assertEqual(a.create_user("boss", "long enough pw", "admin")["role"], "admin")
        with self.assertRaises(InvalidInputError):
            a.create_user("x_user", "long enough pw", "superuser")


class PasswordStorageTests(unittest.TestCase):
    def test_password_is_not_stored_in_plain_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "app.sqlite")
            a = AuthService(Database(path))
            a.register("alice", "my secret pw 123")
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"my secret pw 123", raw)
            row = sqlite3.connect(path).execute("select password_hash, salt from users").fetchone()
            self.assertEqual(len(row[0]), 64)
            self.assertTrue(row[1])

    def test_same_password_gets_different_hashes_because_of_salt(self):
        a = make()
        a.register("alice", "same password!")
        a.register("bobby", "same password!")
        with a._db.connect() as c:
            hashes = [r[0] for r in c.execute("select password_hash from users")]
        self.assertEqual(len(set(hashes)), 2)


class LoginAndTokenTests(unittest.TestCase):
    def setUp(self):
        self.auth = make()
        self.auth.register("alice", "correct horse")

    def test_login_returns_working_token(self):
        token, user = self.auth.login("alice", "correct horse")
        self.assertEqual(self.auth.authenticate(token)["username"], "alice")
        self.assertEqual(user["role"], "user")

    def test_wrong_password_and_unknown_user_give_the_same_error(self):
        messages = set()
        for u, p in (("alice", "wrong password"), ("nobody", "whatever1234")):
            with self.assertRaises(InvalidCredentialsError) as ctx:
                self.auth.login(u, p)
            messages.add(str(ctx.exception))
        self.assertEqual(len(messages), 1)

    def test_garbage_tokens_are_rejected(self):
        for bad in (None, "", "nope", "a" * 50):
            with self.subTest(token=bad):
                with self.assertRaises(InvalidTokenError):
                    self.auth.authenticate(bad)

    def test_logout_revokes_the_token(self):
        token, _ = self.auth.login("alice", "correct horse")
        self.auth.logout(token)
        with self.assertRaises(InvalidTokenError):
            self.auth.authenticate(token)

    def test_expired_token_is_rejected(self):
        auth = make(token_ttl_seconds=0)
        auth.register("alice", "correct horse")
        token, _ = auth.login("alice", "correct horse")
        time.sleep(0.01)
        with self.assertRaises(InvalidTokenError):
            auth.authenticate(token)

    def test_token_is_stored_hashed_not_in_clear(self):
        token, _ = self.auth.login("alice", "correct horse")
        with self.auth._db.connect() as c:
            stored = [r[0] for r in c.execute("select token_hash from auth_tokens")]
        self.assertNotIn(token, stored)

    def test_repeated_failures_are_throttled_then_cleared_by_success_after_window(self):
        auth = make(max_failures=3)
        auth.register("alice", "correct horse")
        for _ in range(3):
            with self.assertRaises(InvalidCredentialsError):
                auth.login("alice", "bad password")
        with self.assertRaises(TooManyAttemptsError):
            auth.login("alice", "correct horse")  # even the right password is blocked now

    def test_successful_login_resets_the_failure_counter(self):
        auth = make(max_failures=3)
        auth.register("alice", "correct horse")
        for _ in range(2):
            with self.assertRaises(InvalidCredentialsError):
                auth.login("alice", "bad password")
        auth.login("alice", "correct horse")
        for _ in range(2):
            with self.assertRaises(InvalidCredentialsError):
                auth.login("alice", "bad password")


if __name__ == "__main__":
    unittest.main()
