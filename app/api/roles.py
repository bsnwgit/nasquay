"""
/api/roles — roles, their per-action permissions, and the action catalogue the
permission grid is drawn from.

The built-in admin role holds every permission implicitly and cannot be changed or
deleted. A caller may only edit roles, and grant permissions, within their own.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.actions import gate
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

ROLE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$"
_BUILTIN = "The built-in admin role holds every permission and cannot be changed or deleted"
_ROLE_TOO_HIGH = "You cannot manage a role with more permissions than your own"


class ActionOut(BaseModel):
    id: str
    source: str
    category: str
    classification: str
    description: str
    long_running: bool
    reviewed: bool


class RoleOut(BaseModel):
    id: int
    name: str
    description: str
    is_builtin: bool
    is_admin: bool
    user_count: int
    permissions: list[str]
    created_at: str
    updated_at: Optional[str] = None


class RoleCreate(BaseModel):
    name: str = Field(pattern=ROLE_NAME_PATTERN)
    description: str = Field(default="", max_length=256)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, pattern=ROLE_NAME_PATTERN)
    description: Optional[str] = Field(default=None, max_length=256)


class PermissionSet(BaseModel):
    allowed: list[str] = Field(default_factory=list, max_length=5000)


def _target(role: dict[str, Any]) -> str:
    return f"role:{role['id']} {role['name']}"


async def _fetch_roles(db, role_id: Optional[int] = None) -> list[dict[str, Any]]:
    sql = """SELECT r.id, r.name, r.description, r.is_builtin, r.is_admin, r.created_at, r.updated_at,
                    (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count
             FROM roles r"""
    params: tuple = ()
    if role_id is not None:
        sql += " WHERE r.id = ?"
        params = (role_id,)
    sql += " ORDER BY r.is_builtin DESC, r.name"
    async with db.execute(sql, params) as cur:
        roles = [dict(row) for row in await cur.fetchall()]

    granted: dict[int, list[str]] = defaultdict(list)
    async with db.execute(
        "SELECT role_id, action_id FROM role_permissions WHERE allowed = 1 ORDER BY action_id"
    ) as cur:
        for row in await cur.fetchall():
            granted[row["role_id"]].append(row["action_id"])

    for role in roles:
        role["is_builtin"] = bool(role["is_builtin"])
        role["is_admin"] = bool(role["is_admin"])
        role["permissions"] = granted.get(role["id"], [])
    return roles


# ── Action catalogue ──────────────────────────────────────────────────────────
# Declared before /{role_id} so "actions" is never read as a role id.

@router.get("/actions", response_model=list[ActionOut])
async def list_actions(db: DbDep, call: Annotated[ActionCall, Depends(require("roles.list"))]):
    async with db.execute(
        """SELECT id, source, category, classification, description, long_running, reviewed
           FROM actions ORDER BY category, id"""
    ) as cur:
        rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        row["long_running"] = bool(row["long_running"])
        row["reviewed"] = bool(row["reviewed"])
    await call.done(detail=f"{len(rows)} actions")
    return rows


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[RoleOut])
async def list_roles(db: DbDep, call: Annotated[ActionCall, Depends(require("roles.list"))]):
    roles = await _fetch_roles(db)
    await call.done(detail=f"{len(roles)} roles")
    return roles


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, db: DbDep, call: Annotated[ActionCall, Depends(require("roles.create"))]
):
    params = body.model_dump()
    try:
        cur = await db.execute(
            "INSERT INTO roles (name, description) VALUES (?, ?)", (body.name.strip(), body.description)
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("role name already exists", params=params)
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    role = (await _fetch_roles(db, cur.lastrowid))[0]
    await call.done(target=_target(role), params=params)
    return role


@router.patch("/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: int, body: RoleUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("roles.update"))],
):
    changes = body.model_dump(exclude_unset=True)
    found = await _fetch_roles(db, role_id)
    if not found:
        await call.failed("role not found", target=f"role:{role_id}", params=changes)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    role = found[0]
    if role["is_builtin"]:
        await call.failed(_BUILTIN, target=_target(role), params=changes)
        raise HTTPException(status.HTTP_409_CONFLICT, _BUILTIN)
    if not await gate.can_manage_role(db, call.caller, role_id):
        raise await call.refused(_ROLE_TOO_HIGH, target=_target(role), params=changes)

    # Column names come from this fixed tuple; every value is a bound parameter.
    sets: list[str] = []
    values: list[Any] = []
    for column in ("name", "description"):
        if changes.get(column) is not None:
            sets.append(f"{column} = ?")
            values.append(changes[column].strip() if column == "name" else changes[column])
    if not sets:
        await call.done(target=_target(role), detail="no changes")
        return role
    sets.append("updated_at = datetime('now')")

    try:
        await db.execute(f"UPDATE roles SET {', '.join(sets)} WHERE id = ?", (*values, role_id))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("role name already exists", target=_target(role), params=changes)
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")

    await call.done(target=_target(role), params=changes)
    return (await _fetch_roles(db, role_id))[0]


@router.put("/{role_id}/permissions", response_model=RoleOut)
async def set_permissions(
    role_id: int, body: PermissionSet, db: DbDep,
    call: Annotated[ActionCall, Depends(require("roles.set_permissions"))],
):
    wanted = set(body.allowed)
    found = await _fetch_roles(db, role_id)
    if not found:
        await call.failed("role not found", target=f"role:{role_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    role = found[0]
    target = _target(role)
    if role["is_builtin"]:
        await call.failed(_BUILTIN, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, _BUILTIN)
    if not await gate.can_manage_role(db, call.caller, role_id):
        raise await call.refused(_ROLE_TOO_HIGH, target=target)

    if wanted:
        placeholders = ",".join("?" * len(wanted))
        async with db.execute(
            f"SELECT id FROM actions WHERE reviewed = 1 AND id IN ({placeholders})", tuple(wanted)
        ) as cur:
            known = {row["id"] for row in await cur.fetchall()}
        unknown = sorted(wanted - known)
        if unknown:
            await call.failed("unknown or unreviewed actions", target=target, params={"actions": unknown})
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"message": "Unknown or unreviewed actions", "actions": unknown},
            )

    if not call.caller.is_admin:
        beyond = sorted(wanted - await gate.role_permissions(db, call.caller.role_id))
        if beyond:
            raise await call.refused(
                "You cannot grant permissions you do not hold yourself",
                target=target, params={"actions": beyond},
            )

    before = set(role["permissions"])
    await db.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
    await db.executemany(
        "INSERT INTO role_permissions (role_id, action_id, allowed, updated_by) VALUES (?, ?, 1, ?)",
        [(role_id, action_id, call.caller.user_id) for action_id in sorted(wanted)],
    )
    await db.commit()

    added, removed = sorted(wanted - before), sorted(before - wanted)
    await call.done(
        target=target,
        params={"added": added, "removed": removed},
        detail=f"{len(added)} added, {len(removed)} removed",
    )
    return (await _fetch_roles(db, role_id))[0]


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("roles.delete"))]
) -> None:
    found = await _fetch_roles(db, role_id)
    if not found:
        await call.failed("role not found", target=f"role:{role_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    role = found[0]
    target = _target(role)
    if role["is_builtin"]:
        await call.failed(_BUILTIN, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, _BUILTIN)
    if role["user_count"]:
        message = "Move this role's users to another role before deleting it"
        await call.failed(message, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, message)
    if not await gate.can_manage_role(db, call.caller, role_id):
        raise await call.refused(_ROLE_TOO_HIGH, target=target)

    try:
        await db.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        message = "The database rejected this change"
        await call.failed(message, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, message)
    await call.done(target=target)
