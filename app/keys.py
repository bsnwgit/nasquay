"""
The SSH keys NASQuay connects with.

A key here is a pair of files in the install's `secrets/keys` directory. NASQuay generates
them, names them, and hands out the public half. The private half is never read by this
module, never returned by the API, and never logged — the only thing that ever opens it is
`ssh` itself, and only because its path is passed on the command line.

That is the whole point of managing them here rather than expecting somebody to place a
key by hand: the public half is what has to travel, and it is the only half anyone should
ever be able to copy out of this application.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import get_settings

# A key name is part of a filename, so it is kept to characters that cannot mean anything
# else to a filesystem or a shell.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class KeyError_(Exception):
    """Something that stopped a key being made, found or removed."""


@dataclass
class Key:
    name: str
    public: str
    fingerprint: str
    comment: str
    private_path: str
    public_path: str
    created_at: str
    # False for the key install.sh made: it is used and shown, but not deleted from here.
    managed: bool = True
    in_use: int = 0


def _dir() -> Path:
    path = Path(get_settings().secrets_dir) / "keys"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def check_name(name: str) -> str:
    if not NAME.match(name or ""):
        raise KeyError_(
            "A key name may hold letters, digits, dot, dash and underscore only"
        )
    return name


def path_for(name: str) -> str:
    """Where a named key's private half lives. The file itself is never opened here."""
    return str(_dir() / check_name(name))


def _fingerprint(public_file: Path) -> tuple[str, str]:
    """The fingerprint and comment ssh-keygen reports for a public key."""
    try:
        out = subprocess.run(
            ["ssh-keygen", "-l", "-f", str(public_file)],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "", ""
    # "256 SHA256:abc… comment (ED25519)"
    parts = out.split(" ", 2)
    if len(parts) < 3:
        return "", ""
    trailing = parts[2].rsplit(" ", 1)[0]
    return parts[1], trailing


def _read(private: Path, managed: bool = True) -> Optional[Key]:
    public_file = private.with_suffix(".pub") if private.suffix != ".pub" else private
    if private.suffix == ".pub":
        private = private.with_suffix("")
    if not public_file.exists() or not private.exists():
        return None
    fingerprint, comment = _fingerprint(public_file)
    return Key(
        name=private.name,
        public=public_file.read_text().strip(),
        fingerprint=fingerprint,
        comment=comment,
        private_path=str(private),
        public_path=str(public_file),
        managed=managed,
        created_at=datetime.fromtimestamp(private.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    )


def listing() -> list[Key]:
    keys: list[Key] = []
    # The install's own key first: it is the default for everything and the one the NAS
    # units already trust, so it belongs in the list even though it is not managed here.
    installed = _read(Path(get_settings().ssh_key_path), managed=False)
    if installed is not None:
        keys.append(installed)
    for public_file in sorted(_dir().glob("*.pub")):
        key = _read(public_file)
        if key is not None:
            keys.append(key)
    return keys


def generate(name: str, comment: str = "nasquay") -> Key:
    """Make a new ed25519 key with no passphrase.

    No passphrase because nothing can type one: NASQuay connects unattended, and a key it
    cannot use is not a safer key, only a broken one. The protection is the file mode and
    the fact that the private half never leaves the host.
    """
    check_name(name)
    private = _dir() / name
    if private.exists() or private.with_suffix(".pub").exists():
        raise KeyError_(f"A key named {name} already exists")
    try:
        result = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment[:64], "-f", str(private)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeyError_(f"Could not run ssh-keygen: {exc}") from exc
    if result.returncode != 0 or not private.exists():
        raise KeyError_(result.stderr.strip()[:200] or "ssh-keygen failed")
    private.chmod(0o600)
    private.with_suffix(".pub").chmod(0o644)

    for key in listing():
        if key.name == name:
            return key
    raise KeyError_("The key was written but could not be read back")


def remove(name: str) -> None:
    check_name(name)
    existing = find(name)
    if existing is not None and not existing.managed:
        raise KeyError_("The install's own key is not removed from here")
    private = _dir() / name
    public = private.with_suffix(".pub")
    if not private.exists() and not public.exists():
        raise KeyError_("No such key")
    for one in (private, public):
        if one.exists():
            one.unlink()


def rename(old: str, new: str) -> Key:
    """Rename a key's files. The caller repoints whatever referred to it.

    Refused for the install's own key: its path comes from the configuration, so renaming
    the file would simply make it unfindable.
    """
    check_name(old)
    check_name(new)
    if old == new:
        raise KeyError_("That is already its name")
    existing = find(old)
    if existing is None:
        raise KeyError_("No such key")
    if not existing.managed:
        raise KeyError_("The install's own key is named by the configuration and cannot be renamed here")
    if find(new) is not None:
        raise KeyError_(f"A key named {new} already exists")

    source, destination = _dir() / old, _dir() / new
    source.rename(destination)
    source.with_suffix(".pub").rename(destination.with_suffix(".pub"))
    renamed = find(new)
    if renamed is None:
        raise KeyError_("The key was renamed but could not be read back")
    return renamed


def find(name: str) -> Optional[Key]:
    for key in listing():
        if key.name == name:
            return key
    return None
