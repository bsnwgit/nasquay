"""
/api/clients — the machines that mount a share, and the mounts themselves.

A client is reached over SSH with NASQuay's own key and only ever asked the same fixed,
read-only questions: is this path mounted, and what does `df` say about it. There is no
free-form command here, exactly as there is none for a NAS.

A mount is stored as an ordinary monitoring target (kind `client_mount`), so it is
watched, read, ruled on and audited like everything else — the only difference is which
machine gets asked.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app import keys
from app.connectors import ssh
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()


def _key_for(name: str) -> str:
    """A client's own key, or the install's if it names none."""
    return keys.path_for(name) if name else get_settings().ssh_key_path


class ClientOut(BaseModel):
    id: int
    name: str
    address: str
    ssh_user: str
    ssh_port: int
    enabled: bool
    last_checked_at: Optional[str] = None
    last_check_ok: Optional[bool] = None
    last_check_detail: str = ""
    key_name: str = ""
    mounts: int = 0


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    ssh_user: str = Field(min_length=1, max_length=64)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    enabled: bool = True
    # Empty means the install's own key, which the NAS units already trust.
    key_name: str = Field(default="", max_length=64)


class MountIn(BaseModel):
    client_id: int = Field(ge=1)
    nas_id: int = Field(ge=1)
    # The share this mount is supposed to be, so the two views can be compared.
    share: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=512)


_SELECT = """SELECT c.*, (SELECT COUNT(*) FROM targets t WHERE t.client_id = c.id) AS mounts
             FROM clients c"""


def _out(row) -> ClientOut:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    if data["last_check_ok"] is not None:
        data["last_check_ok"] = bool(data["last_check_ok"])
    return ClientOut(**{k: v for k, v in data.items() if k in ClientOut.model_fields})


@router.get("", response_model=list[ClientOut])
async def list_clients(
    db: DbDep, call: Annotated[ActionCall, Depends(require("clients.list"))]
):
    async with db.execute(f"{_SELECT} ORDER BY c.name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} clients")
    return [_out(row) for row in rows]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientIn, db: DbDep, call: Annotated[ActionCall, Depends(require("clients.create"))]
):
    try:
        cursor = await db.execute(
            """INSERT INTO clients (name, address, ssh_user, ssh_port, enabled, key_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.name, body.address, body.ssh_user, body.ssh_port, int(body.enabled),
             body.key_name),
        )
    except Exception as exc:
        await call.failed(str(exc), target=body.name)
        raise HTTPException(status.HTTP_409_CONFLICT, "A client with that name already exists")
    await db.commit()
    await call.done(target=body.name, detail=f"{body.ssh_user}@{body.address}")
    async with db.execute(f"{_SELECT} WHERE c.id = ?", (cursor.lastrowid,)) as cur:
        return _out(await cur.fetchone())


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    address: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ssh_user: Optional[str] = Field(default=None, min_length=1, max_length=64)
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)
    enabled: Optional[bool] = None
    key_name: Optional[str] = Field(default=None, max_length=64)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: int, body: ClientUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("clients.update"))],
):
    """Change a client. Renaming one also relabels its mounts, which carry its name for
    display — the mounts themselves are joined by id, so nothing depends on the text."""
    async with db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("client not found", target=f"client:{client_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")

    changes = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not changes:
        return _out(row)
    if "enabled" in changes:
        changes["enabled"] = int(changes["enabled"])

    sets = ", ".join(f"{k} = ?" for k in changes)
    try:
        await db.execute(
            f"UPDATE clients SET {sets}, updated_at = datetime('now') WHERE id = ?",
            (*changes.values(), client_id),
        )
    except Exception as exc:
        await call.failed(str(exc), target=row["name"])
        raise HTTPException(status.HTTP_409_CONFLICT, "A client with that name already exists")

    if "name" in changes and changes["name"] != row["name"]:
        async with db.execute(
            "SELECT id, parent_ref FROM targets WHERE client_id = ?", (client_id,)
        ) as cur:
            mounts = await cur.fetchall()
        for mount in mounts:
            await db.execute(
                "UPDATE targets SET label = ? WHERE id = ?",
                (f"{changes['name']}: {mount['parent_ref']}", mount["id"]),
            )
    await db.commit()
    await call.done(target=row["name"], detail=", ".join(changes))
    async with db.execute(f"{_SELECT} WHERE c.id = ?", (client_id,)) as cur:
        return _out(await cur.fetchone())


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("clients.delete"))],
):
    """Removing a client removes its mounts, and with them their history."""
    async with db.execute("SELECT name FROM clients WHERE id = ?", (client_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("client not found", target=f"client:{client_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    await db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    await db.commit()
    await call.done(target=row["name"], detail="removed")


@router.post("/{client_id}/check")
async def check_client(
    client_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("clients.check"))]
):
    async with db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("client not found", target=f"client:{client_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")

    target = ssh.Target(address=row["address"], user=row["ssh_user"], port=row["ssh_port"],
                        key_path=_key_for(row["key_name"]))
    ok, detail = True, ""
    try:
        detail = await run_in_threadpool(ssh.check, target)
    except ssh.SshError as exc:
        ok, detail = False, str(exc)

    await db.execute(
        """UPDATE clients SET last_checked_at = datetime('now'), last_check_ok = ?,
                              last_check_detail = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (int(ok), detail[:500], client_id),
    )
    await db.commit()
    await call.done(target=row["name"], detail=detail[:200])
    return {"client": row["name"], "ok": ok, "detail": detail}


@router.post("/{client_id}/mounts/discover")
async def discover_mounts(
    client_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("clients.check"))]
):
    """What is mounted on that machine right now, and which of those NASQuay already watches."""
    async with db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("client not found", target=f"client:{client_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")

    target = ssh.Target(address=row["address"], user=row["ssh_user"], port=row["ssh_port"],
                        key_path=_key_for(row["key_name"]))
    try:
        found = await run_in_threadpool(ssh.list_mounts, target)
    except ssh.SshError as exc:
        await call.failed(str(exc), target=row["name"])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    async with db.execute(
        "SELECT ref FROM targets WHERE client_id = ?", (client_id,)
    ) as cur:
        watched = {r["ref"] for r in await cur.fetchall()}

    await call.done(target=row["name"], detail=f"{len(found)} network mounts")
    return {
        "client": row["name"],
        "mounts": [{**one, "watched": one["path"] in watched} for one in found],
    }


@router.delete("/mounts/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mount(
    target_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("clients.delete"))],
):
    """Stop watching a mount. Its readings go with it, so a mount removed by mistake loses
    its history — switching it off under Watched keeps everything instead."""
    async with db.execute(
        "SELECT ref, client_id FROM targets WHERE id = ? AND kind = 'client_mount'",
        (target_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("mount not found", target=f"target:{target_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mount not found")
    await db.execute("DELETE FROM targets WHERE id = ?", (target_id,))
    await db.commit()
    await call.done(target=row["ref"], detail="no longer watched")


@router.post("/mounts", status_code=status.HTTP_201_CREATED)
async def add_mount(
    body: MountIn, db: DbDep, call: Annotated[ActionCall, Depends(require("clients.create"))]
):
    """A mount is a monitoring target, so everything else already knows what to do with it."""
    try:
        ssh.check_mount_path(body.path)
    except ssh.SshError as exc:
        await call.failed(str(exc), target=body.path)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    async with db.execute("SELECT name FROM clients WHERE id = ?", (body.client_id,)) as cur:
        client = await cur.fetchone()
    if client is None:
        await call.failed("client not found", target=f"client:{body.client_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")

    async with db.execute(
        "SELECT id FROM targets WHERE nas_id = ? AND kind = 'client_mount' AND ref = ?",
        (body.nas_id, body.path),
    ) as cur:
        if await cur.fetchone() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "That mount is already watched")

    await db.execute(
        """INSERT INTO targets (nas_id, kind, ref, label, parent_ref, client_id)
           VALUES (?, 'client_mount', ?, ?, ?, ?)""",
        (body.nas_id, body.path, f"{client['name']}: {body.share}", body.share, body.client_id),
    )
    await db.commit()
    await call.done(target=f"{client['name']}:{body.path}", detail=f"for share {body.share}")
    return {"client": client["name"], "path": body.path, "share": body.share}
