"""
/api/notifications — where NASQuay sends word when something is flagged.

The two secrets here follow the same rule as a NAS token: they go in, they never come
out. The response says only whether one is set, and an empty field on an update leaves
the stored value alone, so saving the form does not wipe a password that was not retyped.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto, notify
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

# Everything the form may set, less the secrets, which are handled apart.
PLAIN = (
    "on_error", "on_warning", "on_cleared",
    "email_enabled", "smtp_host", "smtp_port", "smtp_security", "smtp_user",
    "mail_from", "mail_to",
    "ntfy_enabled", "ntfy_server", "ntfy_topic",
    "slack_enabled",
)


class NotificationsOut(BaseModel):
    on_error: bool
    on_warning: bool
    on_cleared: bool
    email_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_user: str
    mail_from: str
    mail_to: str
    ntfy_enabled: bool
    ntfy_server: str
    ntfy_topic: str
    slack_enabled: bool
    # Whether a secret is set — never the secret.
    has_smtp_password: bool
    has_ntfy_token: bool
    has_slack_webhook: bool
    last_sent_at: Optional[str] = None
    last_result: str = ""


class NotificationsIn(BaseModel):
    on_error: Optional[bool] = None
    on_warning: Optional[bool] = None
    on_cleared: Optional[bool] = None
    email_enabled: Optional[bool] = None
    smtp_host: Optional[str] = Field(default=None, max_length=255)
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_security: Optional[str] = Field(default=None, pattern="^(none|starttls|tls)$")
    smtp_user: Optional[str] = Field(default=None, max_length=255)
    mail_from: Optional[str] = Field(default=None, max_length=255)
    mail_to: Optional[str] = Field(default=None, max_length=1000)
    ntfy_enabled: Optional[bool] = None
    ntfy_server: Optional[str] = Field(default=None, max_length=255)
    ntfy_topic: Optional[str] = Field(default=None, max_length=128)
    slack_enabled: Optional[bool] = None
    # Empty means "leave what is stored"; a value replaces it.
    smtp_password: Optional[str] = Field(default=None, max_length=512)
    ntfy_token: Optional[str] = Field(default=None, max_length=512)
    slack_webhook: Optional[str] = Field(default=None, max_length=512)


async def _row(db):
    async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
        row = await cur.fetchone()
    if row is None:
        await db.execute("INSERT INTO notifications (id) VALUES (1)")
        await db.commit()
        async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
            row = await cur.fetchone()
    return row


def _out(row) -> NotificationsOut:
    data = dict(row)
    for flag in ("on_error", "on_warning", "on_cleared", "email_enabled", "ntfy_enabled",
                 "slack_enabled"):
        data[flag] = bool(data[flag])
    data["has_smtp_password"] = bool(data.pop("smtp_password", ""))
    data["has_ntfy_token"] = bool(data.pop("ntfy_token", ""))
    data["has_slack_webhook"] = bool(data.pop("slack_webhook", ""))
    return NotificationsOut(**{k: v for k, v in data.items() if k in NotificationsOut.model_fields})


@router.get("", response_model=NotificationsOut)
async def read(db: DbDep, call: Annotated[ActionCall, Depends(require("notifications.read"))]):
    row = await _row(db)
    await call.done(detail="read")
    return _out(row)


@router.patch("", response_model=NotificationsOut)
async def update(
    body: NotificationsIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("notifications.update"))],
):
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in PLAIN}
    for flag in ("on_error", "on_warning", "on_cleared", "email_enabled", "ntfy_enabled",
                 "slack_enabled"):
        if flag in changes:
            changes[flag] = int(changes[flag])
    # A blank secret is "unchanged", not "erase it" — a form saved without retyping the
    # password must not silently disable the channel it belongs to.
    if body.smtp_password:
        changes["smtp_password"] = crypto.encrypt_str(body.smtp_password)
    if body.ntfy_token:
        changes["ntfy_token"] = crypto.encrypt_str(body.ntfy_token)
    if body.slack_webhook:
        changes["slack_webhook"] = crypto.encrypt_str(body.slack_webhook)

    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)
        await db.execute(
            f"UPDATE notifications SET {sets}, updated_at = datetime('now') WHERE id = 1",
            tuple(changes.values()),
        )
        await db.commit()
    await call.done(
        detail=", ".join(
            k for k in changes
            if "password" not in k and "token" not in k and "webhook" not in k
        )
    )
    return _out(await _row(db))


@router.post("/test")
async def test(db: DbDep, call: Annotated[ActionCall, Depends(require("notifications.test"))]):
    """Send one message now, on every enabled channel, and say exactly what happened."""
    row = await _row(db)
    settings = dict(row)
    if not (settings["email_enabled"] or settings["ntfy_enabled"]
            or settings["slack_enabled"]):
        await call.failed("no channel is enabled")
        raise HTTPException(status.HTTP_409_CONFLICT, "No channel is enabled")

    message = notify.Message(
        title="test",
        body="This is a test from NASQuay. If you are reading it, a real flag will reach you too.",
        severity="info",
    )
    ok, said = await run_in_threadpool(notify.deliver, settings, message)
    await db.execute(
        "UPDATE notifications SET last_sent_at = datetime('now'), last_result = ? WHERE id = 1",
        (said[:500],),
    )
    await db.commit()
    await call.done(detail=said[:200])
    return {"ok": ok, "detail": said}
