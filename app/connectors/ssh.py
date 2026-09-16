"""
Runs the handful of read-only commands on a NAS that its MCP server has no tool for:
filesystem usage, the real size of a share, and a live file count.

There is no free-form command here, by design. Each command is built from a fixed
template, the arguments are checked, and the system `ssh` binary is used with the host's
own key — so NASQuay needs no SSH library and no password ever passes through it.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

# A share or volume path on a QNAP: /share/<something>/<something>...
_PATH = re.compile(r"^/share/[A-Za-z0-9._@+-]+(?:/[A-Za-z0-9 ._@+-]+)*$")

DEFAULT_TIMEOUT = 60


class SshError(Exception):
    """A command that could not be run, or that failed on the NAS."""


@dataclass
class Target:
    address: str
    user: str
    port: int = 22
    key_path: str = ""
    timeout: int = DEFAULT_TIMEOUT


def check_path(path: str) -> str:
    """A share path, or an error. Nothing else is ever interpolated into a command."""
    if not _PATH.match(path or ""):
        raise SshError(f"Not a share path: {path!r}")
    return path


def _run(target: Target, remote_command: str, timeout: Optional[int] = None) -> str:
    argv = [
        "ssh",
        "-o", "BatchMode=yes",                 # never prompt: no password can be typed
        "-o", "StrictHostKeyChecking=yes",     # an unknown or changed host key is a failure
        "-o", f"ConnectTimeout={min(15, target.timeout)}",
        "-p", str(target.port),
    ]
    if target.key_path:
        argv += ["-i", target.key_path, "-o", "IdentitiesOnly=yes"]
    argv += [f"{target.user}@{target.address}", remote_command]

    try:
        finished = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout or target.timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise SshError("The NAS did not answer in time") from exc
    except OSError as exc:
        raise SshError(f"Could not run ssh — {exc}") from exc

    if finished.returncode != 0:
        # QNAP prints a harmless "Could not chdir to home directory" when the account has
        # no home folder; it is not a failure on its own.
        message = (finished.stderr or "").strip().splitlines()
        message = [line for line in message if "Could not chdir" not in line]
        raise SshError(" ".join(message) or f"ssh exited {finished.returncode}")
    return finished.stdout


def df_kib(target: Target, path: str) -> dict[str, int]:
    """Filesystem usage for a volume, in bytes.

    `df -k` is used rather than `-h` so no human-readable units are parsed, and QNAP
    wraps long device names onto their own line, so the numbers are taken from the last
    fields of the joined output.
    """
    out = _run(target, f"df -k {shlex.quote(check_path(path))}")
    numbers: list[int] = []
    for line in out.splitlines()[1:]:
        for field in line.split():
            if field.isdigit():
                numbers.append(int(field))
    if len(numbers) < 3:
        raise SshError("Could not read df output from the NAS")
    total, used, available = numbers[0], numbers[1], numbers[2]
    return {
        "total_bytes": total * 1024,
        "used_bytes": used * 1024,
        "available_bytes": available * 1024,
    }


def du_bytes(target: Target, path: str, timeout: int = 3600) -> int:
    """The real size of a share. Slow on a large share — always run as a job."""
    out = _run(target, f"du -sk {shlex.quote(check_path(path))}", timeout=timeout)
    first = out.split()
    if not first or not first[0].isdigit():
        raise SshError("Could not read du output from the NAS")
    return int(first[0]) * 1024


def file_count(target: Target, path: str, timeout: int = 3600) -> dict[str, int]:
    """Live file and directory counts, with and without QNAP's own housekeeping trees."""
    quoted = shlex.quote(check_path(path))
    out = _run(
        target,
        f"find {quoted} -type f | wc -l; "
        f"find {quoted} -type f | grep -cE '/(@Recycle|\\.@__thumb)/'; "
        f"find {quoted} -mindepth 1 -type d | wc -l",
        timeout=timeout,
    )
    numbers = [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
    if len(numbers) < 3:
        raise SshError("Could not read the file counts from the NAS")
    files, housekeeping, directories = numbers[0], numbers[1], numbers[2]
    return {
        "files": files,
        "files_excluding_housekeeping": files - housekeeping,
        "directories": directories,
    }


def check(target: Target) -> str:
    """Prove the key works. Returns what the NAS says it is."""
    return _run(target, "uname -sm; echo ok", timeout=20).strip()
