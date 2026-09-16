"""
/api/users — NASQuay user accounts: list, create, update, reset password, delete, plus
the signed-in user's own profile and password.

A caller may only manage users whose role is no more powerful than their own
(gate.can_manage_role), and no change may leave NASQuay without an enabled admin.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.actions import audit, gate
from app.auth.local import USERNAME_PATTERN, hash_password, password_problem, verify_password
from app.dependencies import ActionCall, CurrentCaller, DbDep, require

router = APIRouter()

_USER_SELECT = """
    SELECT u.id, u.username, u.display_name, u.email, u.role_id, r.name AS role_name,
           r.is_admin, u.is_active, u.created_at, u.updated_at, u.last_login
    FROM users u JOIN roles r ON r.id = u.role_id
"""
_LAST_ADMIN = "NASQuay must keep at least one enabled admin"
_ROLE_TOO_HIGH = "You cannot assign a role with more permissions than your own"
_USER_TOO_HIGH = "You cannot manage a user whose role has more permissions than your own"


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str
    role_id: int
    role_name: str
    is_admin: bool
    is_active: bool
    created_at: str
    updated_at: Optional[str] = None
    last_login: Optional[str] = None


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=254)
    password: str = Field(min_length=1, max_length=256)
    role_id: int = Field(ge=1)


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=254)
    role_id: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class PasswordSet(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _out(row) -> dict[str, Any]:
    data = dict(row)
    data["is_admin"] = bool(data["is_admin"])
    data["is_active"] = bool(data["is_active"])
    return data


def _target(user_id: int, username: str) -> str:
    return f"user:{user_id} {username}"


async def _fetch_user(db, user_id: int):
    async with db.execute(_USER_SELECT + " WHERE u.id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def _role_exists(db, role_id: int) -> bool:
    async with db.execute("SELECT 1 FROM roles WHERE id = ?", (role_id,)) as cur:
        return await cur.fetchone() is not None


async def _removes_last_admin(db, user, *, new_role_id=None, new_active=None, deleting=False) -> bool:
    """Whether a change would leave no enabled admin.

    The database refuses such a change too; asking first gives a clear answer instead
    of a constraint error.
    """
    if not user["is_active"] or not user["is_admin"]:
        return False
    losing = deleting or new_active is False
    if not losing and new_role_id is not None and new_role_id != user["role_id"]:
        async with db.execute("SELECT is_admin FROM roles WHERE id = ?", (new_role_id,)) as cur:
            row = await cur.fetchone()
        losing = row is not None and not row["is_admin"]
    if not losing:
        return False
    async with db.execute(
        """SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
           WHERE u.is_active = 1 AND r.is_admin = 1 AND u.id != ?""",
        (user["id"],),
    ) as cur:
        (others,) = await cur.fetchone()
    return others == 0


# ── The signed-in user ────────────────────────────────────────────────────────
# Always available once signed in: these are not actions a role can withhold.

@router.get("/me", response_model=UserOut)
async def get_me(caller: CurrentCaller, db: DbDep):
    return _out(await _fetch_user(db, caller.user_id))


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(body: PasswordChange, caller: CurrentCaller, db: DbDep) -> None:
    target = _target(caller.user_id, caller.username)
    async with db.execute("SELECT hashed_password FROM users WHERE id = ?", (caller.user_id,)) as cur:
        row = await cur.fetchone()
    if row is None or not await run_in_threadpool(verify_password, body.current_password, row["hashed_password"]):
        await audit.record(db, caller, "account.change_password", "denied",
                           reason="current password incorrect", target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    hashed = await run_in_threadpool(hash_password, body.new_password)
    # Bumping token_version signs out every session, this one included.
    await db.execute(
        """UPDATE users SET hashed_password = ?, token_version = token_version + 1,
                            updated_at = datetime('now')
           WHERE id = ?""",
        (hashed, caller.user_id),
    )
    await db.commit()
    await audit.record(db, caller, "account.change_password", "allowed", outcome="ok", target=target)


# ── Collection ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[UserOut])
async def list_users(db: DbDep, call: Annotated[ActionCall, Depends(require("users.list"))]):
    async with db.execute(_USER_SELECT + " ORDER BY u.username") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} users")
    return [_out(r) for r in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, db: DbDep, call: Annotated[ActionCall, Depends(require("users.create"))]
):
    params = body.model_dump(exclude={"password"})
    problem = password_problem(body.password)
    if problem:
        await call.failed(problem, params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    if not await _role_exists(db, body.role_id):
        await call.failed("role does not exist", params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role does not exist")
    if not await gate.can_manage_role(db, call.caller, body.role_id):
        raise await call.refused(_ROLE_TOO_HIGH, params=params)

    hashed = await run_in_threadpool(hash_password, body.password)
    try:
        cur = await db.execute(
            "INSERT INTO users (username, display_name, email, hashed_password, role_id) VALUES (?, ?, ?, ?, ?)",
            (body.username, body.display_name, body.email, hashed, body.role_id),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("username already exists", params=params)
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that username already exists")

    user = await _fetch_user(db, cur.lastrowid)
    await call.done(target=_target(user["id"], user["username"]), params=params)
    return _out(user)


# ── Single user ───────────────────────────────────────────────────────────────

@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, body: UserUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("users.update"))],
):
    changes = body.model_dump(exclude_unset=True)
    user = await _fetch_user(db, user_id)
    if user is None:
        await call.failed("user not found", target=f"user:{user_id}", params=changes)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    target = _target(user["id"], user["username"])

    if not await gate.can_manage_role(db, call.caller, user["role_id"]):
        raise await call.refused(_USER_TOO_HIGH, target=target, params=changes)

    new_role_id = changes.get("role_id")
    role_changes = new_role_id is not None and new_role_id != user["role_id"]
    if role_changes:
        if not await _role_exists(db, new_role_id):
            await call.failed("role does not exist", target=target, params=changes)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role does not exist")
        if not await gate.can_manage_role(db, call.caller, new_role_id):
            raise await call.refused(_ROLE_TOO_HIGH, target=target, params=changes)

    if await _removes_last_admin(db, user, new_role_id=new_role_id, new_active=changes.get("is_active")):
        await call.failed(_LAST_ADMIN, target=target, params=changes)
        raise HTTPException(status.HTTP_409_CONFLICT, _LAST_ADMIN)

    # Column names come from this fixed tuple; every value is a bound parameter.
    sets: list[str] = []
    values: list[Any] = []
    for column in ("display_name", "email", "role_id", "is_active"):
        if changes.get(column) is not None:
            sets.append(f"{column} = ?")
            values.append(int(changes[column]) if column == "is_active" else changes[column])
    if not sets:
        await call.done(target=target, detail="no changes")
        return _out(user)
    # A new role or a disable takes effect at once: every existing session ends.
    if role_changes or changes.get("is_active") is False:
        sets.append("token_version = token_version + 1")
    sets.append("updated_at = datetime('now')")

    try:
        await db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*values, user_id))
        await db.commit()
    except sqlite3.IntegrityError as exc:
        await db.rollback()
        message = _LAST_ADMIN if "last_admin" in str(exc) else "The database rejected this change"
        await call.failed(message, target=target, params=changes)
        raise HTTPException(status.HTTP_409_CONFLICT, message)

    await call.done(target=target, params=changes)
    return _out(await _fetch_user(db, user_id))


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int, body: PasswordSet, db: DbDep,
    call: Annotated[ActionCall, Depends(require("users.reset_password"))],
) -> None:
    user = await _fetch_user(db, user_id)
    if user is None:
        await call.failed("user not found", target=f"user:{user_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    target = _target(user["id"], user["username"])
    if not await gate.can_manage_role(db, call.caller, user["role_id"]):
        raise await call.refused(_USER_TOO_HIGH, target=target)
    problem = password_problem(body.new_password)
    if problem:
        await call.failed(problem, target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)

    hashed = await run_in_threadpool(hash_password, body.new_password)
    await db.execute(
        """UPDATE users SET hashed_password = ?, token_version = token_version + 1,
                            updated_at = datetime('now')
           WHERE id = ?""",
        (hashed, user_id),
    )
    await db.commit()
    await call.done(target=target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("users.delete"))]
) -> None:
    user = await _fetch_user(db, user_id)
    if user is None:
        await call.failed("user not found", target=f"user:{user_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    target = _target(user["id"], user["username"])
    if user_id == call.caller.user_id:
        await call.failed("cannot delete own account", target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    if not await gate.can_manage_role(db, call.caller, user["role_id"]):
        raise await call.refused(_USER_TOO_HIGH, target=target)
    if await _removes_last_admin(db, user, deleting=True):
        await call.failed(_LAST_ADMIN, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, _LAST_ADMIN)

    try:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
    except sqlite3.IntegrityError as exc:
        await db.rollback()
        message = _LAST_ADMIN if "last_admin" in str(exc) else "The database rejected this change"
        await call.failed(message, target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, message)
    await call.done(target=target)
