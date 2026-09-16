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
# A mount point on a client machine, which is not a NAS and has no /share. Still an
# absolute path of ordinary characters only, and never one that climbs out of itself.
_MOUNT = re.compile(r"^/[A-Za-z0-9 ._@+()-]+(?:/[A-Za-z0-9 ._@+()-]+)*$")

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


def check_mount_path(path: str) -> str:
    """A client mount point, or an error."""
    if not _MOUNT.match(path or "") or ".." in path:
        raise SshError(f"Not a mount path: {path!r}")
    return path


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


def du_bytes(target: Target, path: str, timeout: int = 3600) -> dict[str, int]:
    """The real size of a share, and how many paths it could not read.

    The trailing slash matters: QNAP's /share/<name> is a symlink onto the volume, and
    `du` does not follow one — without it this returns the size of the link, which is
    zero. The unreadable count matters just as much: a share with directories this
    account cannot enter returns a total that is short by an unknown amount, and a
    silently short total would look exactly like data disappearing.
    """
    out = _run(
        target,
        f"du -sk {shlex.quote(check_path(path))}/ 2>&1 | "
        f"awk '$1 ~ /^[0-9]+$/ {{ v = $1; next }} {{ e++ }} END {{ print v + 0; print e + 0 }}'",
        timeout=timeout,
    )
    numbers = [int(line.strip()) for line in out.splitlines() if line.strip().lstrip("-").isdigit()]
    if len(numbers) < 2:
        raise SshError("Could not read du output from the NAS")
    return {"bytes": numbers[0] * 1024, "unreadable": numbers[1]}


def file_count(target: Target, path: str, timeout: int = 3600) -> dict[str, int]:
    """Live file and directory counts, with and without QNAP's own housekeeping trees.

    One walk for files, one for directories, and the same trailing slash as `du` for the
    same reason. Anything `find` could not enter is counted rather than discarded.
    """
    quoted = shlex.quote(check_path(path))
    out = _run(
        target,
        f"find {quoted}/ -type f 2>&1 | "
        f"awk '/^find: /{{ e++; next }} /\\/(@Recycle|\\.@__thumb)\\//{{ h++ }} "
        f"{{ f++ }} END {{ print f + 0; print h + 0; print e + 0 }}'; "
        f"find {quoted}/ -mindepth 1 -type d 2>/dev/null | wc -l",
        timeout=timeout,
    )
    numbers = [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
    if len(numbers) < 4:
        raise SshError("Could not read the file counts from the NAS")
    files, housekeeping, unreadable, directories = numbers[0], numbers[1], numbers[2], numbers[3]
    return {
        "files": files,
        "files_excluding_housekeeping": files - housekeeping,
        "directories": directories,
        "unreadable": unreadable,
    }


def client_view(target: Target, path: str) -> dict[str, int]:
    """What a client machine sees at a mount point.

    `mount` is consulted rather than trusting `df` alone: on both macOS and Linux, `df` of
    a path that is not mounted quietly answers about the filesystem underneath it, so a
    share that has dropped would report the client's own disk and look healthy.
    """
    quoted = shlex.quote(check_mount_path(path))
    out = _run(
        target,
        f"mount | grep -c -F ' on {check_mount_path(path)} '; df -k {quoted} 2>/dev/null | tail -1",
    )
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        raise SshError("The client returned nothing")
    try:
        mounted = int(lines[0].strip())
    except ValueError as exc:
        raise SshError("Could not tell whether the path is mounted") from exc

    numbers: list[int] = []
    for line in lines[1:]:
        for field in line.split():
            if field.isdigit():
                numbers.append(int(field))
    if len(numbers) < 3:
        return {"mounted": 1 if mounted else 0, "total_bytes": 0, "used_bytes": 0,
                "available_bytes": 0}
    return {
        "mounted": 1 if mounted else 0,
        "total_bytes": numbers[0] * 1024,
        "used_bytes": numbers[1] * 1024,
        "available_bytes": numbers[2] * 1024,
    }


# What counts as a mount worth offering: a filesystem that came from somewhere else.
NETWORK_FILESYSTEMS = ("nfs", "nfs4", "smbfs", "cifs", "afpfs", "webdav", "fuse.sshfs")


def list_mounts(target: Target) -> list[dict[str, str]]:
    """Every network filesystem currently mounted on a client.

    `mount` is parsed rather than /proc/mounts because this has to work on macOS as well as
    Linux, and the two formats differ:

        Linux   device on /path type nfs4 (rw,...)
        macOS   device on /path (nfs, rw, ...)

    Both put the path between " on " and either " type " or " (", which is the only part
    of the line this needs to be sure about.
    """
    out = _run(target, "mount")
    found: list[dict[str, str]] = []
    for line in out.splitlines():
        if " on " not in line:
            continue
        source, rest = line.split(" on ", 1)
        if " type " in rest:
            path, tail = rest.split(" type ", 1)
            kind = tail.split(" ", 1)[0].split("(", 1)[0].strip()
        elif " (" in rest:
            path, tail = rest.rsplit(" (", 1)
            kind = tail.split(",", 1)[0].strip(") ").strip()
        else:
            continue
        kind = kind.strip().lower()
        if kind not in NETWORK_FILESYSTEMS:
            continue
        found.append({"source": source.strip(), "path": path.strip(), "type": kind})
    return found


def check(target: Target) -> str:
    """Prove the key works. Returns what the NAS says it is."""
    return _run(target, "uname -sm; echo ok", timeout=20).strip()
