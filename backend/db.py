"""
Small SQLite helper used by the backend for users, login tokens and
session history. Uses only Python's standard library (sqlite3), so it
needs no extra package and can be tested anywhere.

Pass a file path for a persistent database, or ":memory:" for a
throw-away one (used by default in tests and when persistence is off).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    salt           TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'user',
    created_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT,
    title        TEXT,
    status       TEXT NOT NULL,
    question     TEXT,
    options_json TEXT,
    result_json  TEXT,
    extra_json   TEXT,
    error        TEXT,
    run_id       TEXT,
    output_dir   TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.RLock()
        self._memory_conn = None
        if path == ":memory:":
            # One shared connection: every new ":memory:" connection would
            # otherwise be a separate, empty database.
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        with self._lock:
            conn = self._memory_conn or sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()
