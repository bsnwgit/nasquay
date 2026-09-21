"""
/api/certificates — the certificates an administrator has uploaded for NASQuay to trust.

A NAS is verified one of three ways: its certificate's fingerprint is pinned, it is
checked against one of these, or it is checked against the host's own trust store. This
module holds the middle case, so an organisation's own authority is uploaded once and
every NAS it issued for is verified by chain and name rather than pinned leaf by leaf.

Nothing here is a credential — a certificate is public — so unlike a token it goes in and
comes back out. An upload carrying a private key is refused.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import certs
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

_SELECT = """
    SELECT c.id, c.name, c.pem, c.fingerprint, c.subject, c.issuer, c.not_before,
           c.not_after, c.is_ca, c.added_at,
           (SELECT COUNT(*) FROM nas WHERE nas.tls_cert_id = c.id)
         + (SELECT COUNT(*) FROM ai_providers p WHERE p.tls_cert_id = c.id) AS in_use
    FROM certificates c
"""


class CertOut(BaseModel):
    id: int
    name: str
    pem: str
    fingerprint: str
    subject: str
    issuer: str
    not_before: str
    not_after: str
    is_ca: bool
    added_at: str
    in_use: int = 0


class CertIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    pem: str = Field(min_length=1, max_length=64_000)


def _out(row) -> dict[str, Any]:
    data = dict(row)
    data["is_ca"] = bool(data["is_ca"])
    return data


@router.get("", response_model=list[CertOut])
async def list_certificates(
    db: DbDep, call: Annotated[ActionCall, Depends(require("certificates.list"))]
):
    async with db.execute(_SELECT + " ORDER BY c.name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} certificates")
    return [_out(row) for row in rows]


@router.post("", response_model=CertOut, status_code=status.HTTP_201_CREATED)
async def add_certificate(
    body: CertIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("certificates.create"))],
):
    """Read the uploaded certificate, then store it with what it says about itself."""
    try:
        seen = certs.describe(body.pem)
    except certs.CertError as exc:
        await call.failed(str(exc), target=body.name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    try:
        cur = await db.execute(
            """INSERT INTO certificates (name, pem, fingerprint, subject, issuer,
                                         not_before, not_after, is_ca, added_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name.strip(), seen.pem, seen.fingerprint, seen.subject, seen.issuer,
                seen.not_before, seen.not_after, int(seen.is_ca), call.caller.user_id,
            ),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a certificate with that name already exists", target=body.name)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A certificate with that name already exists")

    async with db.execute(_SELECT + " WHERE c.id = ?", (cur.lastrowid,)) as got:
        row = await got.fetchone()
    await call.done(target=f"certificate:{cur.lastrowid} {body.name}",
                    detail=f"{seen.subject} · expires {seen.not_after}")
    return _out(row)


@router.delete("/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(
    cert_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("certificates.delete"))],
) -> None:
    """Refused while a NAS still names it: removing it would leave that NAS unverifiable,
    and the failure would only appear the next time it was contacted."""
    async with db.execute(_SELECT + " WHERE c.id = ?", (cert_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("certificate not found", target=f"certificate:{cert_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")

    target = f"certificate:{cert_id} {row['name']}"
    if row["in_use"]:
        await call.failed("certificate is in use", target=target)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{row['in_use']} NAS unit(s) or AI provider(s) are verified against it")

    await db.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
    await db.commit()
    await call.done(target=target)
