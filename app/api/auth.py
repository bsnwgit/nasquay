"""
/api/auth — sign in, refresh a session, sign out.

The access token is returned in the response body and sent back as a Bearer header.
The refresh token lives only in an HTTP-only cookie scoped to /api/auth.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.actions import audit
from app.actions.context import Caller
from app.auth.local import (
    burn_time, create_access_token, create_refresh_token, decode_token, verify_password,
)
from app.config import get_settings
from app.dependencies import DbDep, client_ip, load_caller

router = APIRouter()

REFRESH_COOKIE = "nasquay_refresh"
_COOKIE_PATH = "/api/auth"

# ── Sign-in throttling ────────────────────────────────────────────────────────
# Kept in memory: the web service runs a single worker. Failures are counted per
# address and username, and per address, over a sliding window.
_WINDOW_SECONDS = 300
_MAX_PER_ACCOUNT = 5
_MAX_PER_ADDRESS = 20
_failures: dict[str, deque[float]] = defaultdict(deque)


def _recent_failures(key: str, now: float) -> int:
    attempts = _failures.get(key)
    if not attempts:
        return 0
    while attempts and now - attempts[0] > _WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        del _failures[key]
        return 0
    return len(attempts)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str
    is_admin: bool


def _session(caller: Caller, token_version: int) -> SessionOut:
    return SessionOut(
        access_token=create_access_token(caller.user_id, token_version),
        expires_in=get_settings().access_token_expire_minutes * 60,
        username=caller.username,
        role=caller.role_name,
        is_admin=caller.is_admin,
    )


def _set_refresh_cookie(request: Request, response: Response, user_id: int, token_version: int) -> None:
    # Behind the TLS proxy the app itself sees plain HTTP; the proxy says what the
    # browser used.
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(user_id, token_version),
        max_age=get_settings().refresh_token_expire_days * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="strict",
    )


@router.post("/login", response_model=SessionOut)
async def login(body: LoginRequest, request: Request, response: Response, db: DbDep):
    now = time.monotonic()
    ip = client_ip(request)
    account_key, address_key = f"{ip}|{body.username.lower()}", f"{ip}|*"
    anonymous = Caller(kind="anonymous", via="web", username=body.username, client_ip=ip)

    if (_recent_failures(account_key, now) >= _MAX_PER_ACCOUNT
            or _recent_failures(address_key, now) >= _MAX_PER_ADDRESS):
        await audit.record(db, anonymous, "auth.login", "denied", reason="too many failed attempts")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again in a few minutes.",
        )

    async with db.execute(
        "SELECT id, hashed_password, is_active, token_version FROM users WHERE username = ?",
        (body.username,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        await run_in_threadpool(burn_time)
        reason = "unknown username"
    elif not await run_in_threadpool(verify_password, body.password, row["hashed_password"]):
        reason = "wrong password"
    elif not row["is_active"]:
        reason = "account disabled"
    else:
        reason = ""

    if reason:
        _failures[account_key].append(now)
        _failures[address_key].append(now)
        # The reason is for the audit log only; the caller learns nothing about which
        # part was wrong.
        await audit.record(db, anonymous, "auth.login", "denied", reason=reason)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    _failures.pop(account_key, None)
    await db.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (row["id"],))
    await db.commit()

    caller = await load_caller(db, row["id"], row["token_version"], request)
    if caller is None:  # disabled between the check above and now
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    await audit.record(db, caller, "auth.login", "allowed", outcome="ok")
    _set_refresh_cookie(request, response, row["id"], row["token_version"])
    return _session(caller, row["token_version"])


@router.post("/refresh", response_model=SessionOut)
async def refresh(request: Request, response: Response, db: DbDep):
    token = request.cookies.get(REFRESH_COOKIE)
    decoded = decode_token(token, "refresh") if token else None
    caller = await load_caller(db, decoded[0], decoded[1], request) if decoded else None
    if caller is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired — sign in again")
    user_id, token_version = decoded
    _set_refresh_cookie(request, response, user_id, token_version)
    return _session(caller, token_version)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)
