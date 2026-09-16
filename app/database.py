"""
SQLite app database: the connection helper, the FastAPI dependency, and the migration
runner. Numbered .sql files in migrations/ are applied once each, in order, and
recorded in _migrations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

from app.config import get_settings

log = logging.getLogger("nasquay")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def connect() -> aiosqlite.Connection:
    """Open a connection with the pragmas every connection needs.

    foreign_keys is per connection in SQLite. A connection opened without it silently
    ignores the ON DELETE rules the schema depends on.
    """
    conn = await aiosqlite.connect(get_settings().db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    return conn


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI dependency — one connection per request."""
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    """Create the database if needed and apply pending migrations. Safe to repeat."""
    Path(get_settings().db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await connect()
    try:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS _migrations (
                   filename   TEXT PRIMARY KEY,
                   applied_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        await conn.commit()

        for mfile in sorted(MIGRATIONS_DIR.glob("*.sql")):
            async with conn.execute(
                "SELECT 1 FROM _migrations WHERE filename = ?", (mfile.name,)
            ) as cur:
                if await cur.fetchone():
                    continue
            await conn.executescript(mfile.read_text())
            await conn.execute("INSERT INTO _migrations (filename) VALUES (?)", (mfile.name,))
            await conn.commit()
            log.info("Applied migration %s", mfile.name)
    finally:
        await conn.close()
