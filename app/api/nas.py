"""
/api/nas — the NAS units NASQuay talks to: add, change, remove, and test.

Credentials go in but never come out: the MCP token is stored encrypted and the API
reports only whether one is set. Adding a NAS with a pinned certificate is a two-step
move — read the fingerprint it presents, then save it with the NAS — so an admin sees
what they are trusting.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.config import get_settings
from app.connectors import qnap_mcp, ssh
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

_NAS_SELECT = """
    SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint,
           length(mcp_token) > 0 AS has_token, ssh_user, ssh_port, enabled,
           last_checked_at, last_check_ok, last_check_detail, created_at, updated_at
    FROM nas
"""


class NasOut(BaseModel):
    id: int
    name: str
    address: str
    mcp_port: int
    tls_mode: str
    tls_fingerprint: str
    has_token: bool
    ssh_user: str
    ssh_port: int
    enabled: bool
    last_checked_at: Optional[str] = None
    last_check_ok: Optional[bool] = None
    last_check_detail: str = ""
    created_at: str
    updated_at: Optional[str] = None


class NasCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    mcp_port: int = Field(default=8443, ge=1, le=65535)
    tls_mode: str = Field(default="pinned", pattern="^(pinned|system)$")
    tls_fingerprint: str = Field(default="", max_length=128)
    mcp_token: str = Field(default="", max_length=512)
    ssh_user: str = Field(default="", max_length=64)
    ssh_port: int = Field(default=22, ge=1, le=65535)


class NasUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    address: Optional[str] = Field(default=None, min_length=1, max_length=255)
    mcp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    tls_mode: Optional[str] = Field(default=None, pattern="^(pinned|system)$")
    tls_fingerprint: Optional[str] = Field(default=None, max_length=128)
    # "" leaves the stored token alone; a value replaces it.
    mcp_token: Optional[str] = Field(default=None, max_length=512)
    ssh_user: Optional[str] = Field(default=None, max_length=64)
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)
    enabled: Optional[bool] = None


class FingerprintIn(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=8443, ge=1, le=65535)


class FingerprintOut(BaseModel):
    address: str
    port: int
    fingerprint: str


class CheckOut(BaseModel):
    mcp_ok: bool
    mcp_detail: str
    tool_count: Optional[int] = None
    server: str = ""
    ssh_ok: Optional[bool] = None
    ssh_detail: str = ""


def _out(row) -> dict[str, Any]:
    data = dict(row)
    data["has_token"] = bool(data["has_token"])
    data["enabled"] = bool(data["enabled"])
    if data["last_check_ok"] is not None:
        data["last_check_ok"] = bool(data["last_check_ok"])
    return data


def _target(row) -> str:
    return f"nas:{row['id']} {row['name']}"


async def _fetch(db, nas_id: int):
    async with db.execute(_NAS_SELECT + " WHERE id = ?", (nas_id,)) as cur:
        return await cur.fetchone()


async def _token(db, nas_id: int) -> str:
    async with db.execute("SELECT mcp_token FROM nas WHERE id = ?", (nas_id,)) as cur:
        row = await cur.fetchone()
    return crypto.decrypt_str(row["mcp_token"]) if row else ""


def _mcp_target(row, token: str) -> qnap_mcp.Target:
    return qnap_mcp.Target(
        address=row["address"],
        port=row["mcp_port"],
        token=token,
        tls_mode=row["tls_mode"],
        fingerprint=row["tls_fingerprint"],
    )


# ── Collection ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[NasOut])
async def list_nas(db: DbDep, call: Annotated[ActionCall, Depends(require("nas.list"))]):
    async with db.execute(_NAS_SELECT + " ORDER BY name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} NAS units")
    return [_out(row) for row in rows]


@router.post("/fingerprint", response_model=FingerprintOut)
async def read_fingerprint(
    body: FingerprintIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("nas.create"))],
):
    """The certificate a NAS presents, so an admin can see it before trusting it."""
    try:
        fingerprint = await run_in_threadpool(qnap_mcp.fingerprint_of, body.address, body.port)
    except qnap_mcp.McpError as exc:
        await call.failed(str(exc), params=body.model_dump())
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    await call.done(target=f"{body.address}:{body.port}", detail="read certificate fingerprint")
    return FingerprintOut(address=body.address, port=body.port, fingerprint=fingerprint)


@router.post("", response_model=NasOut, status_code=status.HTTP_201_CREATED)
async def create_nas(
    body: NasCreate, db: DbDep, call: Annotated[ActionCall, Depends(require("nas.create"))]
):
    params = body.model_dump(exclude={"mcp_token"})
    if body.tls_mode == "pinned" and not body.tls_fingerprint.strip():
        message = "A pinned certificate needs its fingerprint — read it from the NAS first"
        await call.failed(message, params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    try:
        cur = await db.execute(
            """INSERT INTO nas (name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token,
                                ssh_user, ssh_port)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name.strip(), body.address.strip(), body.mcp_port, body.tls_mode,
                body.tls_fingerprint.replace(":", "").lower().strip(),
                crypto.encrypt_str(body.mcp_token) if body.mcp_token else "",
                body.ssh_user.strip(), body.ssh_port,
            ),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a NAS with that name already exists", params=params)
        raise HTTPException(status.HTTP_409_CONFLICT, "A NAS with that name already exists")

    row = await _fetch(db, cur.lastrowid)
    await call.done(target=_target(row), params=params)
    return _out(row)


# ── One NAS ───────────────────────────────────────────────────────────────────

@router.patch("/{nas_id}", response_model=NasOut)
async def update_nas(
    nas_id: int, body: NasUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("nas.update"))],
):
    changes = body.model_dump(exclude_unset=True)
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    target = _target(row)

    # Column names come from this fixed tuple; every value is a bound parameter.
    sets: list[str] = []
    values: list[Any] = []
    for column in ("name", "address", "mcp_port", "tls_mode", "tls_fingerprint", "ssh_user",
                   "ssh_port", "enabled"):
        if changes.get(column) is not None:
            value = changes[column]
            if column == "tls_fingerprint":
                value = str(value).replace(":", "").lower().strip()
            elif column == "enabled":
                value = int(bool(value))
            elif isinstance(value, str):
                value = value.strip()
            sets.append(f"{column} = ?")
            values.append(value)

    # An empty token means "leave the stored one alone", so it can never be cleared by a
    # form that simply did not show it.
    if changes.get("mcp_token"):
        sets.append("mcp_token = ?")
        values.append(crypto.encrypt_str(changes["mcp_token"]))

    if not sets:
        await call.done(target=target, detail="no changes")
        return _out(row)
    sets.append("updated_at = datetime('now')")

    try:
        await db.execute(f"UPDATE nas SET {', '.join(sets)} WHERE id = ?", (*values, nas_id))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a NAS with that name already exists", target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, "A NAS with that name already exists")

    await call.done(target=target, params={k: v for k, v in changes.items() if k != "mcp_token"})
    return _out(await _fetch(db, nas_id))


@router.delete("/{nas_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nas(
    nas_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("nas.delete"))]
) -> None:
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    target = _target(row)
    await db.execute("DELETE FROM nas WHERE id = ?", (nas_id,))
    await db.commit()
    await call.done(target=target)


@router.post("/{nas_id}/check", response_model=CheckOut)
async def check_nas(
    nas_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("nas.check"))]
):
    """Try the MCP handshake, and the SSH login when an account is set."""
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    target = _target(row)
    token = await _token(db, nas_id)

    result = CheckOut(mcp_ok=False, mcp_detail="")
    if not token:
        result.mcp_detail = "No token is set for this NAS"
    else:
        def probe() -> tuple[dict[str, Any], int]:
            connection = qnap_mcp.Connection(_mcp_target(row, token))
            try:
                info = connection.open()
                return info, len(connection.list_tools())
            finally:
                connection.close()

        try:
            server_info, tool_count = await run_in_threadpool(probe)
            result.mcp_ok = True
            result.tool_count = tool_count
            result.server = f"{server_info.get('name', '')} {server_info.get('version', '')}".strip()
            result.mcp_detail = f"{tool_count} tools"
        except qnap_mcp.McpError as exc:
            result.mcp_detail = str(exc)

    if row["ssh_user"]:
        ssh_target = ssh.Target(
            address=row["address"], user=row["ssh_user"], port=row["ssh_port"],
            key_path=get_settings().ssh_key_path,
        )
        try:
            result.ssh_detail = await run_in_threadpool(ssh.check, ssh_target)
            result.ssh_ok = True
        except ssh.SshError as exc:
            result.ssh_ok = False
            result.ssh_detail = str(exc)

    ok = result.mcp_ok and (result.ssh_ok is not False)
    detail = f"MCP: {result.mcp_detail}"
    if result.ssh_detail:
        detail += f" · SSH: {result.ssh_detail}"
    await db.execute(
        """UPDATE nas SET last_checked_at = datetime('now'), last_check_ok = ?,
                          last_check_detail = ?
           WHERE id = ?""",
        (int(ok), detail[:500], nas_id),
    )
    await db.commit()
    # The caller was allowed to run the check either way; what the audit log must not do
    # is record a failed connection as a success.
    if ok:
        await call.done(target=target, detail=detail)
    else:
        await call.failed(detail, target=target)
    return result
