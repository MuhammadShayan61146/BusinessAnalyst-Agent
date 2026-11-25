"""
AuthService: user accounts and login tokens.

- Passwords are stored only as salted PBKDF2-HMAC-SHA256 hashes.
- Login returns a random bearer token. Only the SHA-256 hash of the token
  is stored, so a leaked database does not leak usable tokens.
- Tokens expire (AUTH_TOKEN_TTL_HOURS) and can be revoked by logging out.
- Repeated failed logins for a username are throttled.
- Usernames listed in ADMIN_USERNAMES cannot be self-registered; admins are
  created from the command line (scripts/create_user.py).

No FastAPI import: fully testable on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_PBKDF2_ROUNDS = 200_000
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Base class for authentication problems."""


class InvalidCredentialsError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


class UsernameTakenError(AuthError):
    pass


class RegistrationDisabledError(AuthError):
    pass


class TooManyAttemptsError(AuthError):
    pass


class InvalidInputError(AuthError):
    """Username or password does not meet the rules."""


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, db, admin_usernames=(), allow_registration=True,
                 token_ttl_seconds=12 * 3600, max_failures=5, failure_window_seconds=300):
        self._db = db
        self._admins = {a.lower() for a in admin_usernames}
        self._allow_registration = allow_registration
        self._ttl = token_ttl_seconds
        self._max_failures = max_failures
        self._window = failure_window_seconds
        self._failures: dict = {}  # username(lower) -> [timestamps]

    # -- validation -------------------------------------------------------------
    @staticmethod
    def _check_username(username):
        if not isinstance(username, str) or not _USERNAME_RE.match(username):
            raise InvalidInputError("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.")

    @staticmethod
    def _check_password(password):
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidInputError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    # -- accounts ---------------------------------------------------------------
    def _insert_user(self, username, password, role):
        salt = secrets.token_bytes(16)
        user_id = str(uuid.uuid4())
        try:
            with self._db.connect() as conn:
                conn.execute(
                    "INSERT INTO users(user_id, username, password_hash, salt, role, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (user_id, username, _hash_password(password, salt), salt.hex(), role, time.time()),
                )
        except Exception as e:  # sqlite3.IntegrityError on the UNIQUE username
            if "UNIQUE" in str(e).upper():
                raise UsernameTakenError("That username is already taken.") from e
            raise
        return {"user_id": user_id, "username": username, "role": role}

    def register(self, username: str, password: str) -> dict:
        """Self-registration. Always creates a normal (non-admin) user."""
        if not self._allow_registration:
            raise RegistrationDisabledError("Self-registration is disabled on this server.")
        self._check_username(username)
        self._check_password(password)
        if username.lower() in self._admins:
            # Reserved: otherwise anyone could grab an admin name first.
            raise UsernameTakenError("That username is already taken.")
        return self._insert_user(username, password, "user")

    def create_user(self, username: str, password: str, role: str = "user") -> dict:
        """Trusted creation path (command-line script). Allows role 'admin'."""
        if role not in ("user", "admin"):
            raise InvalidInputError("role must be 'user' or 'admin'")
        self._check_username(username)
        self._check_password(password)
        return self._insert_user(username, password, role)

    # -- login / tokens -----------------------------------------------------------
    def _recent_failures(self, key):
        now = time.time()
        recent = [t for t in self._failures.get(key, []) if now - t < self._window]
        self._failures[key] = recent
        return recent

    def login(self, username: str, password: str):
        """Returns (token, user_dict). Raises InvalidCredentialsError with one
        uniform message whether the username or the password was wrong."""
        key = (username or "").lower()
        if len(self._recent_failures(key)) >= self._max_failures:
            raise TooManyAttemptsError("Too many failed attempts. Try again in a few minutes.")

        row = None
        if isinstance(username, str) and isinstance(password, str):
            with self._db.connect() as conn:
                row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        # Always do one hash, even for unknown users, so response time does not
        # reveal which usernames exist.
        salt = bytes.fromhex(row["salt"]) if row else b"\x00" * 16
        candidate = _hash_password(password if isinstance(password, str) else "", salt)
        ok = bool(row) and hmac.compare_digest(candidate, row["password_hash"])
        if not ok:
            self._failures.setdefault(key, []).append(time.time())
            raise InvalidCredentialsError("Incorrect username or password.")

        self._failures.pop(key, None)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._db.connect() as conn:
            conn.execute("INSERT INTO auth_tokens(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                         (_hash_token(token), row["user_id"], now, now + self._ttl))
        return token, {"user_id": row["user_id"], "username": row["username"], "role": row["role"]}

    def authenticate(self, token: str) -> dict:
        if not isinstance(token, str) or not token:
            raise InvalidTokenError("Missing or invalid token.")
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT u.user_id, u.username, u.role, t.expires_at FROM auth_tokens t "
                "JOIN users u ON u.user_id = t.user_id WHERE t.token_hash = ?",
                (_hash_token(token),)).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise InvalidTokenError("Missing or invalid token.")
        return {"user_id": row["user_id"], "username": row["username"], "role": row["role"]}

    def logout(self, token: str) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (_hash_token(token or ""),))
