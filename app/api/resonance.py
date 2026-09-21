"""
/api/resonance — the embedded assistant's settings, and the session codes that mount it.

Three routes, and the difference between them matters:

  GET  /api/resonance/config   what the page needs to draw the panel — address, label,
                               side. No secret, and available to anyone signed in, since
                               without it the panel cannot be drawn for them at all.
  GET  /api/resonance/settings the administrator's view: everything but the key itself.
  POST /api/resonance/code     mints one short-lived, single-use code for the signed-in
                               person, by calling resonance with NASQuay's key.

The key goes in and never comes out, like a NAS token. It never reaches a browser: the
browser receives a code that resonance itself issued, is good once, and expires in
seconds.

What the assistant may *do* is a separate matter, and is not here. This module mounts the
panel; it grants nothing. Until the data surface exists the assistant can talk, and knows
nothing whatever about this installation's NAS units.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.dependencies import ActionCall, CurrentCaller, DbDep, require
from app.integrations.resonance import RESONANCE_MODULE_VERSION
from app.integrations.resonance.client import ResonanceClient
from app.integrations.resonance.errors import ResonanceError, ResonanceNotConfigured

router = APIRouter()

PLAIN = ("enabled", "base_url", "label", "side", "ca_bundle")


class ConfigOut(BaseModel):
    """What the page needs to mount the panel. No secret, nothing to configure with."""

    enabled: bool
    base_url: str = ""
    label: str = "Assistant"
    side: str = "right"


class SettingsOut(BaseModel):
    enabled: bool
    base_url: str
    label: str
    side: str
    ca_bundle: str
    has_key: bool
    module_version: str = RESONANCE_MODULE_VERSION
    last_used_at: Optional[str] = None
    last_result: str = ""
    updated_at: Optional[str] = None


class SettingsIn(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = Field(default=None, max_length=255)
    label: Optional[str] = Field(default=None, max_length=32)
    side: Optional[str] = Field(default=None, pattern="^(left|right)$")
    # "" leaves the stored key alone; a value replaces it.
    embed_key: Optional[str] = Field(default=None, max_length=512)
    ca_bundle: Optional[str] = Field(default=None, max_length=64_000)


class CodeOut(BaseModel):
    """Resonance's own answer, passed through. `src` is the path to frame."""

    code: str
    src: str = ""
    base_url: str
    code_expires_in: Optional[int] = None
    expires_in: Optional[int] = None
    parts: Optional[Any] = None
    cap: Optional[Any] = None


async def _row(db):
    async with db.execute(
        """SELECT enabled, base_url, length(embed_key) > 0 AS has_key, label, side,
                  ca_bundle, last_used_at, last_result, updated_at
           FROM resonance WHERE id = 1"""
    ) as cur:
        return await cur.fetchone()


async def _client(db) -> tuple[ResonanceClient, Any]:
    async with db.execute(
        "SELECT base_url, embed_key, ca_bundle, enabled FROM resonance WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    client = ResonanceClient(
        base_url=row["base_url"] if row else "",
        key=crypto.decrypt_str(row["embed_key"]) if row else "",
        ca_bundle=row["ca_bundle"] if row else "",
    )
    return client, row


# ── The panel ─────────────────────────────────────────────────────────────────

@router.get("/config", response_model=ConfigOut)
async def panel_config(db: DbDep, caller: CurrentCaller):
    """Deliberately not behind an action: this says only whether there is a panel to
    draw and where it lives. A role that may not use the assistant is refused when it
    asks for a code, which is the call that actually does something."""
    row = await _row(db)
    if row is None or not row["enabled"] or not row["base_url"]:
        return ConfigOut(enabled=False)
    return ConfigOut(
        enabled=True, base_url=row["base_url"], label=row["label"], side=row["side"]
    )


@router.post("/code", response_model=CodeOut)
async def session_code(
    db: DbDep, call: Annotated[ActionCall, Depends(require("resonance.use"))]
):
    """One code, for the person asking, now.

    Every mount and every renewal comes through here, which is why it is an action of
    its own: a role that may not talk to the assistant never gets a code, and every code
    that is issued is in the audit log under the name it was issued for.
    """
    client, _ = await _client(db)
    caller = call.caller
    try:
        body = await run_in_threadpool(
            client.create_session, caller.username, [caller.role_name]
        )
    except ResonanceNotConfigured as exc:
        await _record(db, ok=False, detail=exc.admin_message)
        await call.failed(exc.admin_message)
        raise HTTPException(status.HTTP_409_CONFLICT, exc.admin_message)
    except ResonanceError as exc:
        await _record(db, ok=False, detail=exc.admin_message)
        await call.failed(f"{exc.admin_message} {exc.detail}".strip())
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.admin_message)

    await _record(db, ok=True, detail="session code issued")
    await call.done(detail="session code issued")
    return CodeOut(base_url=client.base_url, **{
        key: body.get(key) for key in ("code", "src", "code_expires_in", "expires_in", "parts", "cap")
        if body.get(key) is not None
    })


async def _record(db, *, ok: bool, detail: str) -> None:
    await db.execute(
        """UPDATE resonance SET last_used_at = datetime('now'), last_result = ?
           WHERE id = 1""",
        (("ok · " if ok else "failed · ") + detail[:200],),
    )
    await db.commit()


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=SettingsOut)
async def read_settings(
    db: DbDep, call: Annotated[ActionCall, Depends(require("resonance.read"))]
):
    row = await _row(db)
    await call.done(detail="assistant settings")
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["has_key"] = bool(data["has_key"])
    return SettingsOut(**data)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("resonance.update"))],
):
    changes = body.model_dump(exclude_unset=True)

    # Column names come from this fixed tuple; every value is a bound parameter.
    sets: list[str] = []
    values: list[Any] = []
    for column in PLAIN:
        if changes.get(column) is not None:
            value = changes[column]
            if column == "enabled":
                value = int(bool(value))
            elif column == "base_url":
                value = str(value).strip().rstrip("/")
            elif isinstance(value, str):
                value = value.strip()
            sets.append(f"{column} = ?")
            values.append(value)

    # An empty key means "leave the stored one alone", so a form that never showed it
    # cannot wipe it.
    if changes.get("embed_key"):
        sets.append("embed_key = ?")
        values.append(crypto.encrypt_str(changes["embed_key"]))

    if sets:
        sets.append("updated_at = datetime('now')")
        sets.append("updated_by = ?")
        values.append(call.caller.user_id)
        await db.execute(f"UPDATE resonance SET {', '.join(sets)} WHERE id = 1", values)
        await db.commit()

    await call.done(params={k: v for k, v in changes.items() if k != "embed_key"})
    row = await _row(db)
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["has_key"] = bool(data["has_key"])
    return SettingsOut(**data)


@router.post("/test", response_model=CodeOut)
async def test_settings(
    db: DbDep, call: Annotated[ActionCall, Depends(require("resonance.update"))]
):
    """Ask for a code and throw it away, so an administrator sees whether the key works
    — and what it grants — without waiting for somebody to open the panel."""
    client, _ = await _client(db)
    try:
        body = await run_in_threadpool(
            client.create_session, call.caller.username, [call.caller.role_name]
        )
    except ResonanceError as exc:
        await _record(db, ok=False, detail=exc.admin_message)
        await call.failed(f"{exc.admin_message} {exc.detail}".strip())
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.admin_message)

    await _record(db, ok=True, detail="test succeeded")
    await call.done(detail="test succeeded")
    return CodeOut(base_url=client.base_url, **{
        key: body.get(key) for key in ("code", "src", "code_expires_in", "expires_in", "parts", "cap")
        if body.get(key) is not None
    })
