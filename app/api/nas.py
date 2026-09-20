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
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.config import get_settings
from app.connectors import qnap_mcp, ssh
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

_NAS_SELECT = """
    SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, tls_cert_id,
           (SELECT name FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_cert_name,
           (SELECT pem  FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_ca_pem,
           length(mcp_token) > 0 AS has_token, ssh_user, ssh_port, admin_url, enabled,
           last_checked_at, last_check_ok, last_check_detail, created_at, updated_at
    FROM nas
"""


def _admin_url(value: str) -> str:
    """Accept only a web address, so what the browser is handed is a place to go.

    The link is rendered as an href the moment it is stored, which makes anything else —
    javascript:, data: — a way to run script in someone else's session rather than a
    mistyped setting.
    """
    url = value.strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise ValueError("The administration link must start with http:// or https://")
    return url


class NasOut(BaseModel):
    id: int
    name: str
    address: str
    mcp_port: int
    tls_mode: str
    tls_fingerprint: str
    tls_cert_id: Optional[int] = None
    tls_cert_name: Optional[str] = None
    has_token: bool
    ssh_user: str
    ssh_port: int
    admin_url: str = ""
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
    # With tls_mode "system": an uploaded certificate to verify against, or none for the
    # host's own trust store.
    tls_cert_id: Optional[int] = None
    mcp_token: str = Field(default="", max_length=512)
    ssh_user: str = Field(default="", max_length=64)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    admin_url: str = Field(default="", max_length=255)

    @field_validator("admin_url")
    @classmethod
    def _check_admin_url(cls, value: str) -> str:
        return _admin_url(value)


class NasUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    address: Optional[str] = Field(default=None, min_length=1, max_length=255)
    mcp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    tls_mode: Optional[str] = Field(default=None, pattern="^(pinned|system)$")
    tls_fingerprint: Optional[str] = Field(default=None, max_length=128)
    # 0 clears the certificate and falls back to the host's trust store; leaving it out
    # keeps what is stored.
    tls_cert_id: Optional[int] = None
    # "" leaves the stored token alone; a value replaces it.
    mcp_token: Optional[str] = Field(default=None, max_length=512)
    ssh_user: Optional[str] = Field(default=None, max_length=64)
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)
    # "" clears the link; leaving it out keeps what is stored.
    admin_url: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None

    @field_validator("admin_url")
    @classmethod
    def _check_admin_url(cls, value: Optional[str]) -> Optional[str]:
        return value if value is None else _admin_url(value)


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


async def _certificate_missing(db, cert_id: Optional[int]) -> bool:
    """Checked here rather than left to the foreign key, whose error says only that
    something conflicted and would be reported as a duplicate name."""
    if not cert_id:
        return False
    async with db.execute("SELECT 1 FROM certificates WHERE id = ?", (cert_id,)) as cur:
        return await cur.fetchone() is None


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
        ca_pem=row["tls_ca_pem"] or "",
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
    if await _certificate_missing(db, body.tls_cert_id):
        message = "That certificate no longer exists"
        await call.failed(message, params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    try:
        cur = await db.execute(
            """INSERT INTO nas (name, address, mcp_port, tls_mode, tls_fingerprint, tls_cert_id,
                                mcp_token, ssh_user, ssh_port, admin_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name.strip(), body.address.strip(), body.mcp_port, body.tls_mode,
                body.tls_fingerprint.replace(":", "").lower().strip(),
                body.tls_cert_id or None,
                crypto.encrypt_str(body.mcp_token) if body.mcp_token else "",
                body.ssh_user.strip(), body.ssh_port, body.admin_url,
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
                   "ssh_port", "admin_url", "enabled"):
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

    # 0 is how the form says "no certificate"; None means the field was not sent at all,
    # which leaves the stored choice alone.
    if changes.get("tls_cert_id") is not None:
        if await _certificate_missing(db, changes["tls_cert_id"]):
            await call.failed("certificate not found", target=target)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That certificate no longer exists")
        sets.append("tls_cert_id = ?")
        values.append(changes["tls_cert_id"] or None)

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


# ── What a NAS shows ──────────────────────────────────────────────────────────
#
# Presentation, and a setting of the NAS, so it is nas.list to read and nas.update to
# change rather than a pair of permissions of its own: nothing here grants access to
# anything, and whoever may change a NAS's address may reasonably say which of its shares
# this application lists.

class HiddenOut(BaseModel):
    id: int
    kind: str
    value: str
    added_at: str


class HiddenIn(BaseModel):
    kind: str = Field(pattern="^(share|path)$")
    value: str = Field(min_length=1, max_length=1024)


def _hidden_value(kind: str, value: str) -> str:
    """A share is a name; a path is rooted and has no trailing slash."""
    clean = value.strip()
    if kind == "share":
        clean = clean.strip("/")
        if "/" in clean:
            raise ValueError("A share is named, not a path — /Series-B is just Series-B")
    else:
        clean = "/" + clean.strip("/")
        if clean == "/":
            raise ValueError("The root itself cannot be hidden")
    if not clean:
        raise ValueError("Nothing to hide")
    return clean


@router.get("/{nas_id}/hidden", response_model=list[HiddenOut])
async def list_hidden(
    nas_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("nas.list"))]
):
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    async with db.execute(
        """SELECT id, kind, value, added_at FROM hidden_items
           WHERE nas_id = ? ORDER BY kind, value""",
        (nas_id,),
    ) as cur:
        rows = await cur.fetchall()
    await call.done(target=_target(row), detail=f"{len(rows)} hidden")
    return [dict(r) for r in rows]


@router.post("/{nas_id}/hidden", response_model=HiddenOut, status_code=status.HTTP_201_CREATED)
async def hide_item(
    nas_id: int, body: HiddenIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("nas.update"))],
):
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    target = _target(row)

    try:
        value = _hidden_value(body.kind, body.value)
    except ValueError as exc:
        await call.failed(str(exc), target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    try:
        cur = await db.execute(
            "INSERT INTO hidden_items (nas_id, kind, value, added_by) VALUES (?, ?, ?, ?)",
            (nas_id, body.kind, value, call.caller.user_id),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("already hidden", target=target, params={"kind": body.kind, "value": value})
        raise HTTPException(status.HTTP_409_CONFLICT, f"{value} is already hidden")

    await call.done(target=target, params={"hide": body.kind, "value": value})
    async with db.execute(
        "SELECT id, kind, value, added_at FROM hidden_items WHERE id = ?", (cur.lastrowid,)
    ) as got:
        return dict(await got.fetchone())


@router.delete("/{nas_id}/hidden/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def show_item(
    nas_id: int, item_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("nas.update"))],
) -> None:
    row = await _fetch(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    async with db.execute(
        "SELECT kind, value FROM hidden_items WHERE id = ? AND nas_id = ?", (item_id, nas_id)
    ) as cur:
        item = await cur.fetchone()
    if item is None:
        await call.failed("not hidden", target=_target(row))
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item is not hidden")

    await db.execute("DELETE FROM hidden_items WHERE id = ?", (item_id,))
    await db.commit()
    await call.done(target=_target(row), params={"show": item["kind"], "value": item["value"]})


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
