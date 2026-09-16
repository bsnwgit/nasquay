"""
/api/settings — runtime settings stored in the database.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app import settings_store
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()


@router.get("")
async def read_settings(
    db: DbDep, call: Annotated[ActionCall, Depends(require("settings.read"))]
) -> dict[str, Any]:
    values = await settings_store.get_all(db)
    await call.done()
    return values


@router.patch("")
async def update_settings(
    db: DbDep,
    call: Annotated[ActionCall, Depends(require("settings.update"))],
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    try:
        clean = settings_store.validate(body)
    except settings_store.SettingsError as exc:
        await call.failed("invalid settings", params={"keys": sorted(str(k) for k in body)[:50]})
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors)
    await settings_store.set_many(db, clean, call.caller.user_id)
    await call.done(params=clean, detail=", ".join(sorted(clean)))
    return await settings_store.get_all(db)
