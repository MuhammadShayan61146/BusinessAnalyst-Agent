#!/usr/bin/env python3
"""
Create a user (or an administrator) for the web application.

    cd Business-Analyst-Agent-main
    python3 scripts/create_user.py --admin alice        # asks for the password
    python3 scripts/create_user.py bob                  # a normal user

Administrators are the only people who can upload documents to the RAG
knowledge base. They cannot be created through the public registration
endpoint, which is why this script exists. The password is asked for
interactively (it is not accepted on the command line, so it does not end
up in your shell history).
"""
import argparse
import getpass
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(APP_DIR)
for p in (APP_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from config.settings import APP_DB_PATH  # noqa: E402
from backend.auth_service import AuthError, AuthService  # noqa: E402
from backend.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a web-app user.")
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true", help="create an administrator")
    args = parser.parse_args()

    password = getpass.getpass("Password (min 8 characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    auth = AuthService(Database(APP_DB_PATH))
    try:
        user = auth.create_user(args.username, password, "admin" if args.admin else "user")
    except AuthError as e:
        print(f"Could not create the user: {e}")
        return 1
    print(f"Created {user['role']} '{user['username']}' in {APP_DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
