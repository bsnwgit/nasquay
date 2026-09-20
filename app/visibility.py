"""
What a listing leaves out, and why that is presentation rather than permission.

An administrator can hide a shared folder, or a folder anywhere in the tree, so a NAS full
of system shares and QNAP's own housekeeping directories is not a page full of noise. None
of it grants or withholds access: the permission gate has already decided what this caller
may do by the time anything here runs, and a hidden share is exactly as readable as it was.

It is applied where the listing is produced — in /api/run — rather than in the pages, so
the same choice holds for every caller that asks a NAS what is there, the routines and the
MCP endpoint included.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import aiosqlite

from app import settings_store

# The tools whose output is a listing. Anything else is passed through untouched — this
# module hides entries from a list, it does not edit answers.
LISTING_TOOLS = frozenset({"list_files", "list_shared_folder"})


@dataclass(frozen=True)
class Hidden:
    shares: frozenset[str]   # shared folder names
    paths: frozenset[str]    # File Station paths, e.g. /Series-B/@Recycle
    names: frozenset[str]    # folder names hidden wherever they appear

    @property
    def empty(self) -> bool:
        return not (self.shares or self.paths or self.names)

    def hides(self, path: str, name: str) -> bool:
        low = name.strip().lower()
        if not low:
            return False
        if low in self.names:
            return True
        if path == "/" and low in self.shares:
            return True
        return _join(path, low) in self.paths


NOTHING = Hidden(frozenset(), frozenset(), frozenset())


def _join(path: str, name: str) -> str:
    base = (path or "/").rstrip("/")
    return f"{base}/{name}".lower()


async def rules(db: aiosqlite.Connection, nas_id: int) -> Hidden:
    """What is hidden on this NAS: its own entries, plus the names hidden everywhere."""
    shares: set[str] = set()
    paths: set[str] = set()
    async with db.execute(
        "SELECT kind, value FROM hidden_items WHERE nas_id = ?", (nas_id,)
    ) as cur:
        for row in await cur.fetchall():
            value = row["value"].strip().lower()
            if not value:
                continue
            if row["kind"] == "share":
                shares.add(value)
            else:
                paths.add("/" + value.strip("/"))

    settings = await settings_store.get_all(db)
    names = {n.strip().lower() for n in settings.get("files_hidden_names", []) if n.strip()}
    return Hidden(frozenset(shares), frozenset(paths), frozenset(names))


def apply(tool: str, parsed: Any, arguments: dict[str, Any], hidden: Hidden) -> int:
    """Drop the hidden entries from a listing, and say how many went.

    `total` is corrected with them: it is what the pages page through, and a total that
    still counted what is no longer in the list would send the last page off the end.
    """
    if hidden.empty or tool not in LISTING_TOOLS or not isinstance(parsed, dict):
        return 0

    if tool == "list_shared_folder":
        return _filter(parsed, "sharedfolders", "/", ("name",), hidden)

    path = str(arguments.get("path") or "/")
    # At the root, list_files lists the shares themselves and names them `name`; below it
    # the entries are files and folders, named `filename`.
    return _filter(parsed, "data", path, ("name", "filename"), hidden)


def _filter(
    parsed: dict[str, Any], key: str, path: str, name_keys: tuple[str, ...], hidden: Hidden
) -> int:
    entries = parsed.get(key)
    if not isinstance(entries, list):
        return 0

    kept = [entry for entry in entries if not hidden.hides(path, _name_of(entry, name_keys))]
    removed = len(entries) - len(kept)
    if not removed:
        return 0

    parsed[key] = kept
    total = parsed.get("total")
    if isinstance(total, int) and not isinstance(total, bool):
        parsed["total"] = max(total - removed, len(kept))
    return removed


def _name_of(entry: Any, name_keys: tuple[str, ...]) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in name_keys:
        value: Optional[Any] = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
