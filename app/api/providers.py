"""
/api/providers — the AI services routines run against.

The API key follows the rule every other secret here follows: it goes in, it never comes
out. The response says only whether one is set, and an empty key on an update leaves the
stored one alone. A local server that needs no key can have one removed on purpose, with
clear_api_key, never by accident.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.ai import providers as ai
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

_SELECT = """
    SELECT p.*,
           (SELECT name FROM certificates WHERE certificates.id = p.tls_cert_id) AS tls_cert_name,
           (SELECT pem  FROM certificates WHERE certificates.id = p.tls_cert_id) AS tls_ca_pem
    FROM ai_providers p
"""

# Column names in an UPDATE come from this fixed tuple; every value is a bound parameter.
PLAIN = ("name", "kind", "base_url", "model", "timeout_s", "supports_tools", "enabled")


def _url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ValueError("the base URL must start with http:// or https://")
    return value


class ProviderOut(BaseModel):
    id: int
    name: str
    kind: str
    base_url: str
    model: str
    timeout_s: int
    supports_tools: bool
    enabled: bool
    tls_cert_id: Optional[int] = None
    tls_cert_name: Optional[str] = None
    # Whether a key is set — never the key.
    has_api_key: bool
    last_tested_at: Optional[str] = None
    last_result: str = ""
    tools_ok: Optional[bool] = None


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(pattern="^(openai|anthropic)$")
    base_url: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(default="", max_length=512)
    timeout_s: int = Field(default=120, ge=5, le=900)
    supports_tools: bool = True
    enabled: bool = True
    tls_cert_id: Optional[int] = None

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, value: Optional[str]) -> Optional[str]:
        return _url(value)


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    kind: Optional[str] = Field(default=None, pattern="^(openai|anthropic)$")
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, min_length=1, max_length=128)
    # Empty means "leave what is stored"; a value replaces it.
    api_key: Optional[str] = Field(default=None, max_length=512)
    clear_api_key: bool = False
    timeout_s: Optional[int] = Field(default=None, ge=5, le=900)
    supports_tools: Optional[bool] = None
    enabled: Optional[bool] = None
    # 0 means "no certificate"; absent leaves the stored choice alone.
    tls_cert_id: Optional[int] = None

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, value: Optional[str]) -> Optional[str]:
        return _url(value)


def _out(row) -> dict[str, Any]:
    data = dict(row)
    data["supports_tools"] = bool(data["supports_tools"])
    data["enabled"] = bool(data["enabled"])
    data["has_api_key"] = bool(data.pop("api_key", ""))
    data["tools_ok"] = None if data["tools_ok"] is None else bool(data["tools_ok"])
    return {k: v for k, v in data.items() if k in ProviderOut.model_fields}


def _target(row) -> str:
    return f"provider:{row['id']} {row['name']}"


def to_provider(row) -> ai.Provider:
    """The stored row as the client wants it, key decrypted. Used by routines too."""
    return ai.Provider(
        name=row["name"], kind=row["kind"], base_url=row["base_url"], model=row["model"],
        api_key=crypto.decrypt_str(row["api_key"]), timeout_s=row["timeout_s"],
        ca_pem=row["tls_ca_pem"] or "",
    )


async def _fetch(db, provider_id: int):
    async with db.execute(_SELECT + " WHERE p.id = ?", (provider_id,)) as cur:
        return await cur.fetchone()


async def _certificate_missing(db, cert_id: Optional[int]) -> bool:
    if not cert_id:
        return False
    async with db.execute("SELECT 1 FROM certificates WHERE id = ?", (cert_id,)) as cur:
        return await cur.fetchone() is None


@router.get("", response_model=list[ProviderOut])
async def list_providers(db: DbDep, call: Annotated[ActionCall, Depends(require("providers.list"))]):
    async with db.execute(_SELECT + " ORDER BY p.name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} providers")
    return [_out(row) for row in rows]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("providers.create"))],
):
    if await _certificate_missing(db, body.tls_cert_id):
        await call.failed("certificate not found", target=body.name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That certificate no longer exists")
    try:
        cur = await db.execute(
            """INSERT INTO ai_providers (name, kind, base_url, model, api_key, timeout_s,
                                         supports_tools, enabled, tls_cert_id, added_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name.strip(), body.kind, body.base_url, body.model.strip(),
                crypto.encrypt_str(body.api_key) if body.api_key else "",
                body.timeout_s, int(body.supports_tools), int(body.enabled),
                body.tls_cert_id or None, call.caller.user_id,
            ),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a provider with that name already exists", target=body.name)
        raise HTTPException(status.HTTP_409_CONFLICT, "A provider with that name already exists")

    row = await _fetch(db, cur.lastrowid)
    await call.done(target=_target(row), detail=f"{body.kind} {body.model}")
    return _out(row)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int, body: ProviderUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("providers.update"))],
):
    row = await _fetch(db, provider_id)
    if row is None:
        await call.failed("provider not found", target=f"provider:{provider_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    target = _target(row)
    changes = body.model_dump(exclude_unset=True)

    sets: list[str] = []
    values: list[Any] = []
    for column in PLAIN:
        if changes.get(column) is not None:
            value = changes[column]
            if isinstance(value, bool):
                value = int(value)
            elif isinstance(value, str):
                value = value.strip()
            sets.append(f"{column} = ?")
            values.append(value)

    if changes.get("tls_cert_id") is not None:
        if await _certificate_missing(db, changes["tls_cert_id"]):
            await call.failed("certificate not found", target=target)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That certificate no longer exists")
        sets.append("tls_cert_id = ?")
        values.append(changes["tls_cert_id"] or None)

    if body.api_key:
        sets.append("api_key = ?")
        values.append(crypto.encrypt_str(body.api_key))
    elif body.clear_api_key:
        sets.append("api_key = ''")

    # Anything that changes who answers makes the last test meaningless.
    if any(c in changes for c in ("kind", "base_url", "model", "api_key", "clear_api_key",
                                  "tls_cert_id")):
        sets.append("tools_ok = NULL")
        sets.append("last_result = ''")

    if not sets:
        await call.done(target=target, detail="no changes")
        return _out(row)
    sets.append("updated_at = datetime('now')")
    try:
        await db.execute(f"UPDATE ai_providers SET {', '.join(sets)} WHERE id = ?",
                         (*values, provider_id))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a provider with that name already exists", target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, "A provider with that name already exists")

    await call.done(
        target=target,
        detail=", ".join(k for k in changes if k not in ("api_key",)) or "key",
    )
    return _out(await _fetch(db, provider_id))


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("providers.delete"))],
) -> None:
    row = await _fetch(db, provider_id)
    if row is None:
        await call.failed("provider not found", target=f"provider:{provider_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    await db.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
    await db.commit()
    await call.done(target=_target(row))


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("providers.test"))],
):
    """A trivial request and, where the provider claims tools, a trivial tool call — and
    exactly what happened, recorded against the provider."""
    row = await _fetch(db, provider_id)
    if row is None:
        await call.failed("provider not found", target=f"provider:{provider_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    target = _target(row)

    answered, tools_ok, said = await run_in_threadpool(
        ai.test, to_provider(row), bool(row["supports_tools"])
    )
    await db.execute(
        """UPDATE ai_providers SET last_tested_at = datetime('now'), last_result = ?,
                                   tools_ok = ? WHERE id = ?""",
        (said[:500], None if tools_ok is None else int(tools_ok), provider_id),
    )
    await db.commit()
    if answered:
        await call.done(target=target, detail=said[:200])
    else:
        await call.failed(said[:200], target=target)
    return {"ok": answered, "tools_ok": tools_ok, "detail": said}
