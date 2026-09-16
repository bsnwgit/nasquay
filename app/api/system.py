"""
/api/system — where NASQuay listens, and restarting it to apply that.

The listen address and port are read at startup, so they live in config.yaml rather than
the settings table. Saving them rewrites that file; the change takes effect on the next
start.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import signal
import socket
import subprocess
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import config_file
from app.config import get_settings
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()

# What this process actually bound, captured before anything can rewrite the file.
_RUNNING_HOST = get_settings().host
_RUNNING_PORT = get_settings().port

# Ports below 1024 need privileges the service does not have.
_LOWEST_PORT = 1024


class AddressChoice(BaseModel):
    address: str
    label: str


class NetworkOut(BaseModel):
    host: str
    port: int
    running_host: str
    running_port: int
    restart_required: bool
    choices: list[AddressChoice]
    config_file: Optional[str] = None


class NetworkIn(BaseModel):
    host: str = Field(min_length=1, max_length=45)
    port: int = Field(ge=1, le=65535)


def _machine_addresses() -> list[AddressChoice]:
    """Addresses this machine has. The standard library has no portable way to list
    them, so `ip` is asked; if it is missing, only the two fixed choices are offered."""
    choices = [
        AddressChoice(address="127.0.0.1", label="this host only"),
        AddressChoice(address="0.0.0.0", label="every interface"),
    ]
    try:
        found = subprocess.run(
            ["ip", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return choices
    for line in found.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            address = parts[3].split("/")[0]
            if address not in {c.address for c in choices}:
                choices.append(AddressChoice(address=address, label=parts[1]))
    return choices


def _state() -> NetworkOut:
    saved = config_file.current()
    path = config_file.config_path()
    host = str(saved.get("host", _RUNNING_HOST))
    port = int(saved.get("port", _RUNNING_PORT))
    return NetworkOut(
        host=host,
        port=port,
        running_host=_RUNNING_HOST,
        running_port=_RUNNING_PORT,
        restart_required=(host != _RUNNING_HOST or port != _RUNNING_PORT),
        choices=_machine_addresses(),
        config_file=str(path) if path else None,
    )


def _port_is_free(host: str, port: int) -> bool:
    """Whether the service could bind there. Skipped for the pair it already holds —
    this process is the one occupying it."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


@router.get("/network", response_model=NetworkOut)
async def read_network(
    db: DbDep, call: Annotated[ActionCall, Depends(require("system.network_read"))]
):
    state = _state()
    await call.done()
    return state


@router.patch("/network", response_model=NetworkOut)
async def update_network(
    body: NetworkIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("system.network_update"))],
):
    params = body.model_dump()

    # Only an address this machine actually has, so a typo cannot leave the service
    # unable to start.
    offered = {choice.address for choice in _machine_addresses()}
    if body.host not in offered:
        message = "That is not an address on this machine"
        await call.failed(message, params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)
    try:
        ipaddress.ip_address(body.host)
    except ValueError:
        await call.failed("not an IP address", params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is not an IP address")

    if body.port < _LOWEST_PORT and body.port != _RUNNING_PORT:
        message = f"Choose a port of {_LOWEST_PORT} or above — lower ports need privileges NASQuay does not have"
        await call.failed(message, params=params)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    same_as_running = body.host == _RUNNING_HOST and body.port == _RUNNING_PORT
    if not same_as_running and not _port_is_free(body.host, body.port):
        message = f"Something else is already listening on {body.host}:{body.port}"
        await call.failed(message, params=params)
        raise HTTPException(status.HTTP_409_CONFLICT, message)

    try:
        config_file.update({"host": body.host, "port": body.port})
    except (OSError, RuntimeError, ValueError) as exc:
        await call.failed(str(exc), params=params)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    state = _state()
    await call.done(params=params, detail=f"{body.host}:{body.port}, restart to apply")
    return state


@router.post("/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart(
    db: DbDep, call: Annotated[ActionCall, Depends(require("system.restart"))]
) -> dict[str, str]:
    """Stop this process; the service manager starts it again.

    The unit is set to restart always, so a clean stop is enough — NASQuay never needs
    privileges of its own to restart. Without a service manager, this simply stops.
    """
    await call.done(detail="restart requested")
    # After the response has gone out, not before.
    asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)
    return {"status": "restarting"}
