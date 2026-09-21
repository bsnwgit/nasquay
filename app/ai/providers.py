"""
One client for every AI provider NASQuay can use, speaking two dialects: the OpenAI chat
API (Ollama, LM Studio, vLLM, OpenAI) and the Anthropic Messages API.

Both are reduced to the same shape — a reply's text and the tool calls it asked for — so
nothing above this module knows which kind of provider it is talking to.

Standard library rather than a new dependency, like the MCP and resonance connectors. Sync
on purpose — callers run it in a worker thread.

TLS verification is never switched off. What is configurable is which roots to trust.
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 1024

# The model's reply is shown to an administrator and stored; a runaway one is cut here.
MAX_REPLY_CHARS = 8000


class ProviderError(Exception):
    """Something went wrong that an administrator can act on. The message says what."""


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str                 # openai | anthropic
    base_url: str
    model: str
    api_key: str = ""
    timeout_s: int = 120
    ca_pem: str = ""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema for the arguments


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = ""


def _context(provider: Provider) -> ssl.SSLContext:
    if provider.ca_pem:
        return ssl.create_default_context(cadata=provider.ca_pem)
    return ssl.create_default_context()


def _post(provider: Provider, path: str, payload: dict[str, Any],
          headers: dict[str, str]) -> dict[str, Any]:
    url = provider.base_url.rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    context = _context(provider) if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(request, timeout=provider.timeout_s,
                                    context=context) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode() or "{}")
            err = body.get("error")
            detail = err.get("message", "") if isinstance(err, dict) else str(err or "")
        except Exception:
            detail = ""
        if exc.code in (401, 403):
            raise ProviderError(f"The provider refused the API key (HTTP {exc.code}). {detail}".strip())
        if exc.code == 404:
            raise ProviderError(
                f"Nothing answered at {url} (HTTP 404) — check the base URL and the model. {detail}".strip()
            )
        raise ProviderError(f"The provider answered HTTP {exc.code}. {detail}".strip())
    except ssl.SSLCertVerificationError:
        raise ProviderError(
            "Reached the provider, but this host does not trust its certificate. "
            "Choose the authority that issued it."
        )
    except (socket.timeout, TimeoutError):
        raise ProviderError(
            f"No answer within {provider.timeout_s} s. A small model on modest hardware can "
            "need longer — raise the timeout."
        )
    except (urllib.error.URLError, OSError) as exc:
        reason = str(getattr(exc, "reason", exc))
        raise ProviderError(f"Could not reach {provider.base_url}: {reason}")
    except ValueError:
        raise ProviderError("The provider answered with something that was not JSON.")


def _args(raw: Any) -> dict[str, Any]:
    # OpenAI-style servers send arguments as a JSON string, and small models sometimes
    # send one that does not parse. That is the model's mistake, reported as empty
    # arguments rather than a crash, so the gate still decides what happens next.
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ── OpenAI chat API ───────────────────────────────────────────────────────────

def _openai(provider: Provider, system: str, messages: list[dict[str, Any]],
            tools: list[Tool]) -> Reply:
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": ([{"role": "system", "content": system}] if system else []) + messages,
        "max_tokens": MAX_TOKENS,
    }
    if tools:
        payload["tools"] = [
            {"type": "function",
             "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]
    headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    body = _post(provider, "/chat/completions", payload, headers)

    choices = body.get("choices") or []
    if not choices:
        raise ProviderError("The provider returned no answer.")
    message = choices[0].get("message") or {}
    calls = [
        ToolCall(id=str(c.get("id") or f"call_{i}"),
                 name=str((c.get("function") or {}).get("name", "")),
                 arguments=_args((c.get("function") or {}).get("arguments")))
        for i, c in enumerate(message.get("tool_calls") or [])
    ]
    return Reply(text=str(message.get("content") or "")[:MAX_REPLY_CHARS], tool_calls=calls,
                 stop=str(choices[0].get("finish_reason") or ""))


# ── Anthropic Messages API ────────────────────────────────────────────────────

def _anthropic(provider: Provider, system: str, messages: list[dict[str, Any]],
               tools: list[Tool]) -> Reply:
    payload: dict[str, Any] = {
        "model": provider.model,
        "max_tokens": MAX_TOKENS,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
    headers = {"anthropic-version": ANTHROPIC_VERSION}
    if provider.api_key:
        headers["x-api-key"] = provider.api_key
    body = _post(provider, "/v1/messages", payload, headers)

    text, calls = [], []
    for block in body.get("content") or []:
        if block.get("type") == "text":
            text.append(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(id=str(block.get("id", "")), name=str(block.get("name", "")),
                                  arguments=_args(block.get("input"))))
    return Reply(text="".join(text)[:MAX_REPLY_CHARS], tool_calls=calls,
                 stop=str(body.get("stop_reason") or ""))


def assistant_turn(provider: Provider, reply: Reply) -> dict[str, Any]:
    """The model's own turn, in its dialect, to go back into the conversation."""
    if provider.kind == "anthropic":
        content: list[dict[str, Any]] = []
        if reply.text:
            content.append({"type": "text", "text": reply.text})
        content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    for c in reply.tool_calls]
        return {"role": "assistant", "content": content}
    return {
        "role": "assistant",
        "content": reply.text or None,
        "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in reply.tool_calls
        ],
    }


def tool_results(provider: Provider, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
    """What each tool call returned, in the provider's dialect."""
    if provider.kind == "anthropic":
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": text}
            for call, text in results
        ]}]
    return [{"role": "tool", "tool_call_id": call.id, "content": text} for call, text in results]


def chat(provider: Provider, system: str, messages: list[dict[str, Any]],
         tools: Optional[list[Tool]] = None) -> Reply:
    """One turn: the conversation so far in, the model's reply out."""
    if provider.kind == "openai":
        return _openai(provider, system, messages, tools or [])
    if provider.kind == "anthropic":
        return _anthropic(provider, system, messages, tools or [])
    raise ProviderError(f"Unknown provider kind {provider.kind!r}")


# ── Test ──────────────────────────────────────────────────────────────────────

_PROBE = Tool(
    name="report_number",
    description="Report a number back to NASQuay.",
    parameters={
        "type": "object",
        "properties": {"number": {"type": "integer"}},
        "required": ["number"],
    },
)


def test(provider: Provider, with_tools: bool) -> tuple[bool, Optional[bool], str]:
    """A trivial request, then a trivial tool call.

    Returns (answered, tools_ok, what happened). tools_ok is None when the tool call was
    not tried. The tool is a probe: nothing is ever run on its behalf.
    """
    try:
        reply = chat(provider, "", [{"role": "user", "content": "Reply with the single word: ready"}])
    except ProviderError as exc:
        return False, None, str(exc)
    said = f"answered: {reply.text.strip()[:60]!r}"
    if not with_tools:
        return True, None, said

    try:
        reply = chat(
            provider, "",
            [{"role": "user", "content": "Call report_number with the number 7."}],
            [_PROBE],
        )
    except ProviderError as exc:
        return True, False, f"{said}; the tool call failed: {exc}"
    call = next((c for c in reply.tool_calls if c.name == _PROBE.name), None)
    if call is None:
        return True, False, f"{said}; it did not call the tool when asked to"
    if call.arguments.get("number") != 7:
        return True, False, f"{said}; it called the tool with the wrong arguments {call.arguments}"
    return True, True, f"{said}; tool calling works"
