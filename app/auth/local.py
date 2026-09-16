"""
Local accounts: bcrypt password hashing and JWT access / refresh tokens.

Both tokens carry the user's token_version. Bumping it in the database — on a password
change, a disable or a role change — invalidates every token issued before.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
MIN_PASSWORD_LENGTH = 10
# bcrypt reads only the first 72 bytes. Longer input is refused, not silently truncated.
MAX_PASSWORD_BYTES = 72


def password_problem(plain: str) -> Optional[str]:
    """Why a new password is unacceptable, or None."""
    if len(plain) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(plain.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes"
    return None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# A sign-in for an unknown username checks against this, so it takes as long as a
# wrong password for a real one and does not reveal which usernames exist.
_DUMMY_HASH = bcrypt.hashpw(b"nasquay-timing-equaliser", bcrypt.gensalt())


def burn_time() -> None:
    bcrypt.checkpw(b"nasquay-not-the-password", _DUMMY_HASH)


def _issue(user_id: int, token_version: int, kind: str, lifetime: timedelta) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "type": kind,
        "exp": datetime.now(tz=timezone.utc) + lifetime,
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.algorithm)


def create_access_token(user_id: int, token_version: int) -> str:
    minutes = get_settings().access_token_expire_minutes
    return _issue(user_id, token_version, "access", timedelta(minutes=minutes))


def create_refresh_token(user_id: int, token_version: int) -> str:
    days = get_settings().refresh_token_expire_days
    return _issue(user_id, token_version, "refresh", timedelta(days=days))


def decode_token(token: str, expected: Literal["access", "refresh"]) -> Optional[tuple[int, int]]:
    """(user_id, token_version) for a valid, unexpired token of the expected kind."""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.algorithm])
    except JWTError:
        return None
    if payload.get("type") != expected:
        return None
    try:
        return int(payload["sub"]), int(payload["tv"])
    except (KeyError, TypeError, ValueError):
        return None
