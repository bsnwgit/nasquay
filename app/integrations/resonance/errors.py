"""
Typed errors for the embed client.

Resonance answers every failure as {"error": "<sentence>"} with no machine-readable code,
so the status is the only thing worth branching on. That branching happens once, here,
and each class carries the sentence an administrator should see — the difference between
"it does not work" and "that is the admin port, not the embed server" is most of the
support burden.

`config_error` marks a failure that retrying cannot fix. Those open the breaker quickly,
because resonance applies a per-address backoff to repeated bad-key attempts and NASQuay
is a single address: knocking harder would take the panel down for everyone at once.
"""
from __future__ import annotations

from typing import Optional


class ResonanceError(Exception):
    """Base for every embed failure. `admin_message` is what a page may show."""

    status: Optional[int] = None
    config_error: bool = False
    admin_message: str = "The assistant request failed."

    def __init__(self, detail: str = "", *, admin_message: Optional[str] = None):
        self.detail = detail
        if admin_message:
            self.admin_message = admin_message
        super().__init__(self.admin_message if not detail else f"{self.admin_message} ({detail})")


class ResonanceNotConfigured(ResonanceError):
    config_error = True
    admin_message = "The assistant is not configured — set its address and key."


class ResonanceBadRequest(ResonanceError):
    """400 — includes a key that names people when no user was sent."""

    status = 400
    config_error = True
    admin_message = "Resonance rejected the request — this key expects a named person."


class ResonanceUnauthorized(ResonanceError):
    """401 — resonance answers the same way for a bad id and a bad secret, on purpose."""

    status = 401
    config_error = True
    admin_message = "The key was not recognised — check for a truncated or mistyped paste."


class ResonanceKeyDisabled(ResonanceError):
    status = 403
    config_error = True
    admin_message = "This key is disabled in resonance."


class ResonanceWrongPort(ResonanceError):
    """404 — the commonest misconfiguration, and the least obvious."""

    status = 404
    config_error = True
    admin_message = "That address is resonance's admin port. Use its embed server address."


class ResonanceBackoff(ResonanceError):
    """429 — resonance is refusing this address after failed attempts."""

    status = 429
    config_error = True
    admin_message = (
        "Resonance is refusing attempts from this host after earlier failures. "
        "Fix the key, then wait for its backoff to clear."
    )


class ResonanceUnreachable(ResonanceError):
    """A network-level failure — transient until proven otherwise."""

    admin_message = "Could not reach the resonance server."


class ResonanceBreakerOpen(ResonanceError):
    """Raised here, without calling out, while the breaker is open."""

    admin_message = "Paused after repeated failures."


_BY_STATUS: dict[int, type[ResonanceError]] = {
    400: ResonanceBadRequest,
    401: ResonanceUnauthorized,
    403: ResonanceKeyDisabled,
    404: ResonanceWrongPort,
    429: ResonanceBackoff,
}


def for_status(status: int, detail: str = "") -> ResonanceError:
    """Map a status from /embed/session onto a typed error."""
    cls = _BY_STATUS.get(status)
    if cls is not None:
        return cls(detail)
    return ResonanceError(detail, admin_message=f"Resonance answered unexpectedly ({status}).")
