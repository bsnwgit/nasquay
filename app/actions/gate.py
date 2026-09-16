"""
The permission gate. Nothing changes in NASQuay, and nothing is sent to a NAS, without
check() allowing it first.
"""
from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from app.actions.context import Caller


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


async def check(db: aiosqlite.Connection, caller: Caller, action_id: str) -> Decision:
    async with db.execute("SELECT reviewed FROM actions WHERE id = ?", (action_id,)) as cur:
        action = await cur.fetchone()
    if action is None:
        return Decision(False, "unknown action")
    # Unreviewed actions are offered to no one, admin included: a firmware update must
    # not quietly hand out a new power.
    if not action["reviewed"]:
        return Decision(False, "action not yet reviewed")
    if caller.kind != "user" or caller.role_id is None:
        return Decision(False, "caller has no role")
    if caller.is_admin:
        return Decision(True, "admin role")
    async with db.execute(
        "SELECT allowed FROM role_permissions WHERE role_id = ? AND action_id = ?",
        (caller.role_id, action_id),
    ) as cur:
        row = await cur.fetchone()
    if row and row["allowed"]:
        return Decision(True, f"allowed for role {caller.role_name}")
    return Decision(False, f"not allowed for role {caller.role_name}")


async def role_permissions(db: aiosqlite.Connection, role_id: int) -> set[str]:
    async with db.execute(
        "SELECT action_id FROM role_permissions WHERE role_id = ? AND allowed = 1", (role_id,)
    ) as cur:
        return {row["action_id"] for row in await cur.fetchall()}


async def can_manage_role(db: aiosqlite.Connection, caller: Caller, role_id: int) -> bool:
    """Whether the caller may hand out a role, or manage its holders.

    Only a role no more powerful than the caller's own. Without this, anyone allowed
    users.update could promote themselves to admin, and anyone allowed
    roles.set_permissions could grant themselves everything.
    """
    if caller.is_admin:
        return True
    if caller.role_id is None:
        return False
    async with db.execute("SELECT is_admin FROM roles WHERE id = ?", (role_id,)) as cur:
        row = await cur.fetchone()
    if row is None or row["is_admin"]:
        return False
    return await role_permissions(db, role_id) <= await role_permissions(db, caller.role_id)
