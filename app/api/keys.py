"""
/api/keys — the SSH keys NASQuay connects with.

Only public halves ever leave this module. There is no endpoint that returns a private
key, no endpoint that uploads one, and nothing here reads one: a private key's path is
passed to `ssh` and that is the extent of it.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import keys
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()


class KeyOut(BaseModel):
    name: str
    public: str
    fingerprint: str
    comment: str
    created_at: str
    public_path: str
    managed: bool = True
    in_use: int = 0


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    comment: str = Field(default="nasquay", max_length=64)


async def _in_use(db) -> dict[str, int]:
    async with db.execute(
        "SELECT key_name, COUNT(*) AS n FROM clients WHERE key_name <> '' GROUP BY key_name"
    ) as cur:
        return {row["key_name"]: row["n"] for row in await cur.fetchall()}


@router.get("", response_model=list[KeyOut])
async def list_keys(db: DbDep, call: Annotated[ActionCall, Depends(require("keys.list"))]):
    used = await _in_use(db)
    found = keys.listing()
    await call.done(detail=f"{len(found)} keys")
    return [
        KeyOut(name=k.name, public=k.public, fingerprint=k.fingerprint, comment=k.comment,
               created_at=k.created_at, public_path=k.public_path, managed=k.managed,
               in_use=used.get(k.name, 0))
        for k in found
    ]


@router.post("", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: KeyIn, db: DbDep, call: Annotated[ActionCall, Depends(require("keys.create"))]
):
    try:
        key = keys.generate(body.name, body.comment)
    except keys.KeyError_ as exc:
        await call.failed(str(exc), target=body.name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await call.done(target=body.name, detail=key.fingerprint)
    return KeyOut(name=key.name, public=key.public, fingerprint=key.fingerprint,
                  comment=key.comment, created_at=key.created_at,
                  public_path=key.public_path, managed=key.managed)


class RenameIn(BaseModel):
    new_name: str = Field(min_length=1, max_length=64)


@router.patch("/{name}", response_model=KeyOut)
async def rename_key(
    name: str, body: RenameIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("keys.rename"))],
):
    """Rename the key and repoint every client that named it, or undo the rename.

    The files and the references have to move together: a key renamed without its
    references is a set of clients pointing at a path that no longer exists, and the
    failure would only appear the next time one of them was read.
    """
    try:
        key = keys.rename(name, body.new_name)
    except keys.KeyError_ as exc:
        await call.failed(str(exc), target=name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    try:
        await db.execute(
            "UPDATE clients SET key_name = ?, updated_at = datetime('now') WHERE key_name = ?",
            (body.new_name, name),
        )
        await db.commit()
    except Exception as exc:
        # Put the files back rather than leave the two out of step.
        keys.rename(body.new_name, name)
        await call.failed(f"could not repoint clients: {exc}", target=name)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "The key was not renamed: its clients could not be updated")

    used = await _in_use(db)
    await call.done(target=name, detail=f"renamed to {body.new_name}")
    return KeyOut(name=key.name, public=key.public, fingerprint=key.fingerprint,
                  comment=key.comment, created_at=key.created_at,
                  public_path=key.public_path, managed=key.managed,
                  in_use=used.get(key.name, 0))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    name: str, db: DbDep, call: Annotated[ActionCall, Depends(require("keys.delete"))]
):
    """Refused while a client still uses it: removing it would break that connection with
    no way to tell from the error which key had gone."""
    used = await _in_use(db)
    if used.get(name):
        await call.failed("key is in use", target=name)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{used[name]} client(s) still use that key")
    try:
        keys.remove(name)
    except keys.KeyError_ as exc:
        await call.failed(str(exc), target=name)
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    await call.done(target=name, detail="deleted")
