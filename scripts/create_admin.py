#!/usr/bin/env python3
"""
Create NASQuay's first admin account. install.sh runs this; to run it by hand:

    cd /opt/nasquay
    NASQUAY_CONFIG=/opt/nasquay/config.yaml venv/bin/python scripts/create_admin.py

Does nothing if an enabled admin already exists.
"""
from __future__ import annotations

import asyncio
import getpass
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.actions import audit  # noqa: E402
from app.actions.context import Caller  # noqa: E402
from app.auth.local import USERNAME_PATTERN, hash_password, password_problem  # noqa: E402
from app.database import connect, init_db  # noqa: E402

ADMIN_ROLE_ID = 1  # the built-in admin role, created by migrations/001_initial.sql


def _ask_username() -> str:
    while True:
        name = input("Admin username [admin]: ").strip() or "admin"
        if re.fullmatch(USERNAME_PATTERN, name):
            return name
        print("  Use up to 64 letters, digits, dots, dashes or underscores, starting with a letter or digit.")


def _ask_password() -> str:
    while True:
        first = getpass.getpass("Password: ")
        problem = password_problem(first)
        if problem:
            print(f"  {problem}.")
            continue
        if getpass.getpass("Password again: ") != first:
            print("  The passwords did not match.")
            continue
        return first


async def main() -> int:
    if not sys.stdin.isatty():
        print("create_admin.py needs an interactive terminal.", file=sys.stderr)
        return 2

    await init_db()
    conn = await connect()
    try:
        async with conn.execute(
            """SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
               WHERE u.is_active = 1 AND r.is_admin = 1"""
        ) as cur:
            (admins,) = await cur.fetchone()
        if admins:
            print("An enabled admin account already exists; nothing to do.")
            return 0

        print("Create the first NASQuay admin account.")
        while True:
            username = _ask_username()
            display_name = input("Display name (optional): ").strip()[:128]
            password = _ask_password()
            try:
                cur = await conn.execute(
                    "INSERT INTO users (username, display_name, hashed_password, role_id) VALUES (?, ?, ?, ?)",
                    (username, display_name, hash_password(password), ADMIN_ROLE_ID),
                )
                await conn.commit()
                break
            except sqlite3.IntegrityError:
                await conn.rollback()
                print(f"  A user named '{username}' already exists. Choose another name.")

        installer = Caller(kind="system", via="install", username="install.sh")
        await audit.record(
            conn, installer, "users.create", "allowed",
            reason="first admin created during install", outcome="ok",
            target=f"user:{cur.lastrowid} {username}",
        )
        print(f"Admin account '{username}' created.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
