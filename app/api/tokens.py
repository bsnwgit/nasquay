"""
/api/tokens — personal API tokens for the MCP endpoint.

A token is shown exactly once, in the answer to the request that made it, and only its
hash is stored. Everyone manages their own; an administrator sees and can revoke all of
them, because a token that leaked has to be stoppable by somebody other than its owner.

Revoking deletes the token outright. The audit log keeps the record of it being made,
used and revoked, so nothing is lost by not keeping a dead row on the page.

Only an administrator may make a token that allows destructive actions — an outside tool
has nobody to confirm with.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

PREFIX = "nq_"
SHOWN_CHARS = 10          # how much of a token the list shows, to tell them apart


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenOut(BaseModel):
    id: int
    user_id: int
    username: str
    name: str
    prefix: str
    access: str
    allow_destructive: bool
    created_at: str
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    access: str = Field(default="read", pattern="^(read|write)$")
    allow_destructive: bool = False
    # 0 means it never expires.
    expires_days: int = Field(default=90, ge=0, le=3650)


class TokenMade(TokenOut):
    # The only time the token itself is ever sent.
    token: str


_SELECT = """
    SELECT t.id, t.user_id, u.username, t.name, t.prefix, t.access, t.allow_destructive,
           t.created_at, t.expires_at, t.last_used_at, t.revoked_at
    FROM api_tokens t JOIN users u ON u.id = t.user_id
"""


def _out(row) -> dict[str, Any]:
    data = dict(row)
    data["allow_destructive"] = bool(data["allow_destructive"])
    return data


@router.get("", response_model=list[TokenOut])
async def list_tokens(db: DbDep, call: Annotated[ActionCall, Depends(require("tokens.list"))]):
    """Your own tokens — or, for an administrator, everybody's."""
    # revoked_at is only set on tokens revoked before revoking meant deleting.
    if call.caller.is_admin:
        query, params = _SELECT + " WHERE t.revoked_at IS NULL ORDER BY u.username, t.name", ()
    else:
        query = _SELECT + " WHERE t.user_id = ? AND t.revoked_at IS NULL ORDER BY t.name"
        params = (call.caller.user_id,)
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} tokens")
    return [_out(r) for r in rows]


@router.post("", response_model=TokenMade, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: TokenIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("tokens.create"))],
):
    if body.allow_destructive and not call.caller.is_admin:
        raise await call.refused("only an administrator may make a token that allows destructive actions",
                                 target=body.name)
    if body.allow_destructive and body.access != "write":
        await call.failed("destructive needs write access", target=body.name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A token that allows destructive actions must allow writes too")

    token = PREFIX + secrets.token_urlsafe(32)
    expires = f"+{body.expires_days} days" if body.expires_days else None
    cur = await db.execute(
        """INSERT INTO api_tokens (user_id, name, token_hash, prefix, access,
                                   allow_destructive, created_by, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?,
                   CASE WHEN ? IS NULL THEN NULL ELSE datetime('now', ?) END)""",
        (call.caller.user_id, body.name.strip(), hash_token(token), token[:SHOWN_CHARS],
         body.access, int(body.allow_destructive), call.caller.user_id, expires, expires),
    )
    await db.commit()
    async with db.execute(_SELECT + " WHERE t.id = ?", (cur.lastrowid,)) as got:
        row = await got.fetchone()
    await call.done(target=f"token:{cur.lastrowid} {body.name}",
                    detail=f"{body.access}{', destructive' if body.allow_destructive else ''}, "
                           f"expires {row['expires_at'] or 'never'}")
    return TokenMade(**_out(row), token=token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("tokens.revoke"))],
) -> None:
    async with db.execute(_SELECT + " WHERE t.id = ?", (token_id,)) as cur:
        row = await cur.fetchone()
    # Somebody else's token is "not found" rather than "forbidden", so the list of other
    # people's tokens is not something a probe can map.
    if row is None or (row["user_id"] != call.caller.user_id and not call.caller.is_admin):
        await call.failed("token not found", target=f"token:{token_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    target = f"token:{token_id} {row['name']} of {row['username']}"
    await db.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    await db.commit()
    await call.done(target=target, detail=f"{row['prefix']}… deleted")
