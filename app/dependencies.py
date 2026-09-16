"""
FastAPI dependency helpers: the database connection, the signed-in caller, and
require() — the action requirement every protected route declares.
"""
from __future__ import annotations

import time
from typing import Annotated, Any, Optional

import aiosqlite
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.actions import audit, gate
from app.actions.context import Caller
from app.auth.local import decode_token
from app.database import get_db

DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def load_caller(
    db: aiosqlite.Connection, user_id: int, token_version: int, request: Request
) -> Optional[Caller]:
    """The caller for a token's user — None if the user is gone, disabled, or the token
    predates the user's current token_version."""
    async with db.execute(
        """SELECT u.id, u.username, u.is_active, u.token_version, u.role_id,
                  r.name AS role_name, r.is_admin
           FROM users u JOIN roles r ON r.id = u.role_id
           WHERE u.id = ?""",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None or not row["is_active"] or row["token_version"] != token_version:
        return None
    return Caller(
        kind="user",
        via="web",
        username=row["username"],
        user_id=row["id"],
        role_id=row["role_id"],
        role_name=row["role_name"],
        is_admin=bool(row["is_admin"]),
        client_ip=client_ip(request),
    )


async def get_current_caller(
    request: Request,
    db: DbDep,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Security(_bearer)] = None,
) -> Caller:
    unauthorised = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not signed in, or the session has expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise unauthorised
    decoded = decode_token(credentials.credentials, "access")
    caller = await load_caller(db, decoded[0], decoded[1], request) if decoded else None
    if caller is None:
        raise unauthorised
    return caller


CurrentCaller = Annotated[Caller, Depends(get_current_caller)]


class ActionCall:
    """An allowed action in progress. The route reports how it ended — done(), failed()
    or refused() — and that writes the audit record."""

    def __init__(self, db: aiosqlite.Connection, caller: Caller, action_id: str, reason: str):
        self.db = db
        self.caller = caller
        self.action_id = action_id
        self.reason = reason
        self._started = time.monotonic()

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    async def done(self, *, target: str = "", params: Optional[dict[str, Any]] = None, detail: str = "") -> None:
        await audit.record(
            self.db, self.caller, self.action_id, "allowed", reason=self.reason, outcome="ok",
            target=target, params=params, detail=detail, duration_ms=self._elapsed_ms(),
        )

    async def failed(self, detail: str, *, target: str = "", params: Optional[dict[str, Any]] = None) -> None:
        await audit.record(
            self.db, self.caller, self.action_id, "allowed", reason=self.reason, outcome="error",
            target=target, params=params, detail=detail, duration_ms=self._elapsed_ms(),
        )

    async def refused(self, reason: str, *, target: str = "", params: Optional[dict[str, Any]] = None) -> HTTPException:
        """Record a denial decided inside the route (e.g. a role above the caller's own)
        and return the 403 for the route to raise."""
        await audit.record(
            self.db, self.caller, self.action_id, "denied", reason=reason,
            target=target, params=params, duration_ms=self._elapsed_ms(),
        )
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)


def require(action_id: str):
    """Declare that a route performs action_id. A refused call is audited and answered
    403 before the route body runs."""

    async def dependency(db: DbDep, caller: CurrentCaller) -> ActionCall:
        decision = await gate.check(db, caller, action_id)
        if not decision.allowed:
            await audit.record(db, caller, action_id, "denied", reason=decision.reason)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not permitted: {action_id}",
            )
        return ActionCall(db, caller, action_id, decision.reason)

    return dependency
