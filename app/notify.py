"""
Telling somebody a flag was raised.

Three channels, each optional and independent: email for a record that stays, ntfy for a
push that reaches a phone, and Slack for where people are already looking. Any of them can
be on without the others, and one failing never stops another — a notification system that
falls over silently is worse than none, so what happened is recorded either way.

Three rules hold here:

  **Sending never blocks collection.** All three are blocking calls with a short
  timeout, run in a worker thread, and any exception is caught and recorded. A mail server
  that has gone away must not stop readings being taken.

  **A flag is announced once.** The rules raise a flag once and clear it once, so there is
  no separate rate limit: the same condition holding for a week is one message, not one
  every five minutes. The clearing is worth sending too — knowing a thing fixed itself is
  as useful as knowing it broke.

  **Nothing secret is in the message.** A flag's detail names a volume, a share or a path,
  and never a credential.
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Optional

from app import crypto

log = logging.getLogger("nasquay.notify")

TIMEOUT = 15


@dataclass
class Message:
    title: str
    body: str
    # error | warning | info — decides the push priority and the subject's prefix.
    severity: str = "warning"
    # A document to attach, for the channels that can carry one — email only. The others
    # send the body alone rather than refusing.
    attachment: Optional[tuple[str, bytes, str]] = None   # filename, content, media type


def _priority(severity: str) -> str:
    return {"error": "high", "warning": "default", "info": "low"}.get(severity, "default")


def send_email(settings: dict[str, Any], message: Message) -> str:
    host = (settings.get("smtp_host") or "").strip()
    recipients = [one.strip() for one in (settings.get("mail_to") or "").split(",") if one.strip()]
    if not host or not recipients:
        raise ValueError("A mail server and at least one recipient are needed")

    note = EmailMessage()
    note["Subject"] = f"NASQuay: {message.title}"
    note["From"] = settings.get("mail_from") or settings.get("smtp_user") or "nasquay"
    note["To"] = ", ".join(recipients)
    note.set_content(message.body)
    if message.attachment:
        name, content, media = message.attachment
        kind, _, subtype = media.partition("/")
        note.add_attachment(content, maintype=kind or "application",
                            subtype=subtype or "octet-stream", filename=name)

    port = int(settings.get("smtp_port") or 587)
    security = settings.get("smtp_security") or "starttls"
    password = crypto.decrypt_str(settings.get("smtp_password") or "")

    if security == "tls":
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
    try:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        if settings.get("smtp_user"):
            server.login(settings["smtp_user"], password)
        server.send_message(note)
    finally:
        try:
            server.quit()
        except Exception:  # a server that will not say goodbye has still taken the mail
            pass
    return f"mail to {len(recipients)} recipient(s)"


def send_ntfy(settings: dict[str, Any], message: Message) -> str:
    server = (settings.get("ntfy_server") or "").strip().rstrip("/")
    topic = (settings.get("ntfy_topic") or "").strip()
    if not server or not topic:
        raise ValueError("An ntfy server and topic are needed")

    request = urllib.request.Request(
        f"{server}/{topic}",
        data=message.body.encode("utf-8"),
        method="POST",
        headers={
            "Title": f"NASQuay: {message.title}"[:200],
            "Priority": _priority(message.severity),
            "Tags": "warning" if message.severity == "error" else "information_source",
        },
    )
    token = crypto.decrypt_str(settings.get("ntfy_token") or "")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            if answer.status >= 400:
                raise ValueError(f"the server answered {answer.status}")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"the server answered {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"could not reach {server} — {exc.reason}") from exc
    return f"pushed to {topic}"


def send_slack(settings: dict[str, Any], message: Message) -> str:
    """Post to an incoming webhook.

    The webhook URL is the credential — anyone holding it can post to that channel — so it
    is decrypted here and never goes anywhere else.
    """
    url = crypto.decrypt_str(settings.get("slack_webhook") or "")
    if not url.startswith("https://"):
        raise ValueError("A Slack webhook URL is needed")

    mark = {"error": ":rotating_light:", "warning": ":warning:"}.get(message.severity, ":white_check_mark:")
    payload = json.dumps({"text": f"{mark} *NASQuay: {message.title}*\n{message.body}"})
    request = urllib.request.Request(
        url, data=payload.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            if answer.status >= 400:
                raise ValueError(f"Slack answered {answer.status}")
    except urllib.error.HTTPError as exc:
        # Slack puts the reason in the body, and it is short and useful.
        detail = exc.read().decode("utf-8", "replace").strip()[:120]
        raise ValueError(f"Slack answered {exc.code}{f' — {detail}' if detail else ''}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"could not reach Slack — {exc.reason}") from exc
    return "posted to Slack"


def deliver(settings: dict[str, Any], message: Message) -> tuple[bool, str]:
    """Send on every enabled channel. One failing never stops another."""
    results: list[str] = []
    problems: list[str] = []

    if settings.get("email_enabled"):
        try:
            results.append(send_email(settings, message))
        except Exception as exc:
            problems.append(f"email: {exc}")
            log.warning("Email notification failed: %s", exc)

    if settings.get("ntfy_enabled"):
        try:
            results.append(send_ntfy(settings, message))
        except Exception as exc:
            problems.append(f"ntfy: {exc}")
            log.warning("ntfy notification failed: %s", exc)

    if settings.get("slack_enabled"):
        try:
            results.append(send_slack(settings, message))
        except Exception as exc:
            problems.append(f"slack: {exc}")
            log.warning("Slack notification failed: %s", exc)

    if not results and not problems:
        return False, "no channel is enabled"
    return not problems, " · ".join(results + problems)[:500]


def wanted(settings: dict[str, Any], severity: str, cleared: bool = False) -> bool:
    """Whether this is worth sending at all, by the thresholds that were set."""
    if not (settings.get("email_enabled") or settings.get("ntfy_enabled")
            or settings.get("slack_enabled")):
        return False
    if cleared:
        return bool(settings.get("on_cleared"))
    if severity == "error":
        return bool(settings.get("on_error"))
    return bool(settings.get("on_warning"))


def describe(rule: str, detail: str, target: str = "", cleared: bool = False) -> Message:
    title = f"{rule} cleared" if cleared else rule
    if target:
        title = f"{title} — {target}"
    body = detail or ("The condition no longer holds." if cleared else "No detail was recorded.")
    return Message(title=title, body=body, severity="info" if cleared else "error")
