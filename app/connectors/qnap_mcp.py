"""
Client for QNAP's MCP Assistant, which runs on each NAS.

Written against MCP Assistant 1.0.0.2356 on QTS 5.2.x, where these held:

- Streamable HTTP at /mcp on the HTTPS port; `Authorization: Bearer <token>`.
- `initialize` returns an `Mcp-Session-Id` that every later request must carry.
- HTTP/1.1 works; over HTTP/2 the same requests answered `404 Invalid session ID`, so
  this uses http.client and stays on 1.1.
- Tool annotations are useless: every tool, reads included, reports
  `readOnlyHint=false, destructiveHint=true`. NASQuay classifies tools itself.

Certificates are self-signed, so the default is to pin: the certificate's SHA-256
fingerprint is recorded when the NAS is added and checked on every connection. Nothing
here ever disables verification silently.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
from dataclasses import dataclass, field
from typing import Any, Optional

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "nasquay", "version": "1"}
DEFAULT_TIMEOUT = 30


class McpError(Exception):
    """Anything that stopped a call from succeeding, in words fit for the page."""


@dataclass
class Target:
    address: str
    port: int = 8443
    token: str = ""
    tls_mode: str = "pinned"          # pinned | system
    fingerprint: str = ""             # sha256 hex, lower case, no colons
    timeout: int = DEFAULT_TIMEOUT
    path: str = "/mcp"


def fingerprint_of(address: str, port: int, timeout: int = 10) -> str:
    """The SHA-256 fingerprint of the certificate a NAS presents, for an admin to accept."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((address, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=address) as tls:
                der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as exc:
        raise McpError(f"Could not reach {address}:{port} — {exc}") from exc
    if not der:
        raise McpError(f"{address}:{port} presented no certificate")
    return hashlib.sha256(der).hexdigest()


def _context(target: Target) -> ssl.SSLContext:
    if target.tls_mode == "system":
        return ssl.create_default_context()
    # Pinned: the fingerprint is checked against the presented certificate after the
    # handshake, which is what makes a self-signed certificate safe to use here.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@dataclass
class Connection:
    """One MCP session. Sync on purpose — callers run it in a worker thread."""

    target: Target
    _conn: Optional[http.client.HTTPSConnection] = field(default=None, init=False)
    _session_id: str = field(default="", init=False)
    _next_id: int = field(default=1, init=False)
    server_info: dict[str, Any] = field(default_factory=dict, init=False)

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _open(self) -> None:
        if self._conn is not None:
            return
        target = self.target
        try:
            self._conn = http.client.HTTPSConnection(
                target.address, target.port, context=_context(target), timeout=target.timeout
            )
            self._conn.connect()
        except (OSError, ssl.SSLError) as exc:
            raise McpError(f"Could not reach {target.address}:{target.port} — {exc}") from exc

        if target.tls_mode == "pinned":
            sock = self._conn.sock
            der = sock.getpeercert(binary_form=True) if sock else None
            presented = hashlib.sha256(der).hexdigest() if der else ""
            expected = (target.fingerprint or "").replace(":", "").lower()
            if not expected:
                self.close()
                raise McpError("No certificate fingerprint is recorded for this NAS")
            if presented != expected:
                self.close()
                raise McpError(
                    "The NAS presented a different certificate than the one recorded. "
                    "If the certificate was replaced, accept the new one in its settings."
                )

    def _post(self, payload: dict[str, Any]) -> tuple[int, dict[str, str], str]:
        self._open()
        assert self._conn is not None
        headers = {
            "Authorization": f"Bearer {self.target.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            self._conn.request("POST", self.target.path, body=json.dumps(payload), headers=headers)
            response = self._conn.getresponse()
            body = response.read().decode("utf-8", "replace")
            return response.status, dict(response.getheaders()), body
        except (OSError, http.client.HTTPException) as exc:
            self.close()
            raise McpError(f"The NAS stopped responding — {exc}") from exc

    @staticmethod
    def _message(body: str) -> dict[str, Any]:
        """One JSON-RPC message, whether sent as JSON or as an event stream."""
        for line in body.splitlines():
            line = line[6:] if line.startswith("data: ") else line
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        return {}

    def _rpc(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        self._next_id += 1
        if params is not None:
            payload["params"] = params
        status, headers, body = self._post(payload)

        if status == 401:
            raise McpError("The NAS rejected the token")
        if status == 404:
            raise McpError("The MCP session was not accepted — is MCP Assistant still running?")
        if status >= 400:
            raise McpError(f"The NAS answered {status}")

        message = self._message(body)
        if "error" in message and message["error"]:
            error = message["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(str(detail))
        return message.get("result") or {}

    # ── session ───────────────────────────────────────────────────────────────

    def open(self) -> dict[str, Any]:
        """Handshake. Returns the server's own description of itself."""
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        }
        status, headers, body = self._post(payload)
        if status == 401:
            raise McpError("The NAS rejected the token")
        if status >= 400:
            raise McpError(f"The NAS answered {status} to the handshake")

        self._session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id") or ""
        message = self._message(body)
        if message.get("error"):
            raise McpError(str(message["error"]))
        self.server_info = (message.get("result") or {}).get("serverInfo") or {}
        if not self._session_id:
            raise McpError("The NAS did not return a session id")

        # The server expects this before any other request.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.server_info

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._rpc("tools/list").get("tools") or [])

    def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """The tool's reply as text — QNAP returns JSON documents inside it."""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        parts = [
            part.get("text", "")
            for part in (result.get("content") or [])
            if isinstance(part, dict)
        ]
        text = " ".join(p for p in parts if p)
        # A refusal arrives as a normal result with isError set, and the reason is in the
        # same text field as a success ("nonexistent path: /..."). Carry it out: the page
        # can only explain what went wrong if it is told.
        if result.get("isError"):
            raise McpError(text.strip() or f"{name} failed on the NAS")
        return text or json.dumps(result)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        self._session_id = ""

    def __enter__(self) -> "Connection":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
