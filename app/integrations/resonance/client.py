"""
Client for resonance's /embed/session endpoint, and the breaker in front of it.

One call, one job: hand resonance NASQuay's key and the identity of the person asking,
and get back a short-lived single-use code their browser can spend on /embed?c=<code>.
The key never leaves this host; resonance never sees a NASQuay password.

Standard library rather than a new dependency, like the MCP connector next door. Sync on
purpose — the caller runs it in a worker thread.

TLS verification is never switched off. There is no such switch for the browser that is
about to frame the same server, so disabling it here would only hide a failure every user
is about to meet as a blank frame. What is configurable is which roots to trust, for a
certificate from an internal authority.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from . import APP_SLUG
from .errors import (
    ResonanceBreakerOpen,
    ResonanceError,
    ResonanceNotConfigured,
    ResonanceUnreachable,
    for_status,
)

log = logging.getLogger("nasquay.resonance")

# Resonance normalises user.id to 64 characters and drops the whole user object if it is
# missing, so a long login is truncated here rather than silently discarded there. Roles
# are capped at 16 of 32 characters on its side; matching the caps keeps what is sent
# equal to what gets recorded.
MAX_ID_LEN = 64
MAX_NAME_LEN = 64
MAX_ROLE_LEN = 32
MAX_ROLES = 16

DEFAULT_TIMEOUT = 10.0

# The breaker. A configuration failure is not worth retrying and resonance punishes
# repeated bad keys per address, so one is enough to stop; a network failure might be a
# restart, so it takes a few.
CONFIG_FAILURES_TO_OPEN = 1
NETWORK_FAILURES_TO_OPEN = 4
BREAKER_SECONDS = 60


class _Breaker:
    """Shared by every request, so one bad key does not become a hundred attempts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_until = 0.0
        self._reason = ""

    def check(self) -> None:
        with self._lock:
            if self._opened_until and time.monotonic() < self._opened_until:
                raise ResonanceBreakerOpen(self._reason)

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0
            self._reason = ""

    def failed(self, error: ResonanceError) -> None:
        with self._lock:
            self._failures += 1
            limit = CONFIG_FAILURES_TO_OPEN if error.config_error else NETWORK_FAILURES_TO_OPEN
            if self._failures >= limit:
                self._opened_until = time.monotonic() + BREAKER_SECONDS
                self._reason = error.admin_message
                log.warning("Assistant paused for %ss: %s", BREAKER_SECONDS, error.admin_message)


_breaker = _Breaker()


def build_user_id(username: str) -> str:
    """'nasquay-robert' — application and login together, so resonance's own records
    show both. The prefix is a constant, not a setting: an administrator must not be
    able to make their install report itself as something else."""
    return f"{APP_SLUG}-{username}"[:MAX_ID_LEN]


def _clean_roles(roles: Optional[list[str]]) -> list[str]:
    if not roles:
        return []
    cleaned = [str(role).strip()[:MAX_ROLE_LEN] for role in roles if str(role).strip()]
    return cleaned[:MAX_ROLES]


class ResonanceClient:
    def __init__(self, base_url: str, key: str, *, timeout: float = DEFAULT_TIMEOUT,
                 ca_bundle: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.key = (key or "").strip()
        self.timeout = timeout
        self.ca_bundle = (ca_bundle or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.key)

    def _context(self) -> ssl.SSLContext:
        if self.ca_bundle:
            return ssl.create_default_context(cadata=self.ca_bundle)
        return ssl.create_default_context()

    def create_session(self, username: str, roles: Optional[list[str]] = None) -> dict[str, Any]:
        """POST /embed/session, returning resonance's body as it sent it: code, src,
        code_expires_in, expires_in, parts, cap.

        All of it, not just the code, because the settings page shows what the key
        actually grants — asking, microphone, speech, the session lifetime — from a real
        call rather than asking an administrator to retype it from the other side.
        """
        if not self.configured:
            raise ResonanceNotConfigured()
        _breaker.check()

        payload = {
            "key": self.key,
            "user": {
                "id": build_user_id(username),
                "name": (username or "").strip()[:MAX_NAME_LEN],
                "roles": _clean_roles(roles),
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/embed/session",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=self._context()) as response:
                body = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = (json.loads(exc.read().decode() or "{}") or {}).get("error", "")
            except Exception:
                detail = ""
            error = for_status(exc.code, detail)
            _breaker.failed(error)
            raise error from exc
        except ssl.SSLCertVerificationError as exc:
            error = ResonanceUnreachable(
                str(exc),
                admin_message=(
                    "Reached the resonance server, but this host does not trust its "
                    "certificate. Add the issuing authority below."
                ),
            )
            _breaker.failed(error)
            raise error from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            # One exception type covers name resolution, refused connections and
            # certificates, and they have completely different fixes. The DNS one is
            # easy to miss: the browser resolves names this host may not, so an internal
            # name plus a public resolver here makes every key look wrong.
            text = str(getattr(exc, "reason", exc)).lower()
            if any(s in text for s in ("name or service not known", "nodename nor servname",
                                       "temporary failure in name resolution", "getaddrinfo")):
                message = (
                    "Could not resolve the resonance server's name from this host. The "
                    "browser resolving it is not enough — NASQuay calls it directly."
                )
            elif "certificate" in text or "ssl" in text:
                message = "Reached the resonance server, but its certificate was not trusted."
            else:
                message = (
                    "Could not reach the resonance server — nothing accepted a connection."
                )
            error = ResonanceUnreachable(str(exc), admin_message=message)
            _breaker.failed(error)
            raise error from exc
        except ValueError as exc:
            error = ResonanceUnreachable("resonance answered with something that was not JSON")
            _breaker.failed(error)
            raise error from exc

        if not body.get("code"):
            error = ResonanceUnreachable("resonance returned no code")
            _breaker.failed(error)
            raise error

        _breaker.succeeded()
        return body
