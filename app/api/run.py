"""
/api/run — running a NAS tool from the pages.

The checks themselves live in app/actions/runner.py, which the routines call too, so one
permission check and one audit record cover every route in. This module only turns the
runner's answer into HTTP.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.actions import runner
from app.dependencies import CurrentCaller, DbDep

router = APIRouter()


class RunIn(BaseModel):
    nas_id: int = Field(ge=1)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # A person ticking "yes, do it". Unattended callers have no dialog, so they need a
    # standing allowance instead — see the routines and MCP work.
    confirm: bool = False


class RunOut(BaseModel):
    tool: str
    nas: str
    classification: str
    text: str
    json_result: Optional[Any] = None
    # How many entries an administrator's visibility settings kept out of this listing.
    # Reported rather than silent: a page saying "3 hidden" is the difference between a
    # setting and a listing that is quietly wrong.
    hidden: int = 0


@router.post("", response_model=RunOut)
async def run_tool(body: RunIn, db: DbDep, caller: CurrentCaller):
    try:
        result = await runner.run_tool(db, caller, body.nas_id, body.tool, body.arguments,
                                       body.confirm)
    except runner.Refused as exc:
        raise HTTPException(exc.status, exc.message)
    return RunOut(
        tool=result.tool,
        nas=result.nas,
        classification=result.classification,
        text=result.text,
        json_result=result.parsed,
        hidden=result.hidden,
    )
