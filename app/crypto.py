"""
Fernet encryption for secrets kept in the database — today the NAS MCP tokens.

credential_key is generated once by install.sh and written to config.yaml, separate from
secret_key: signing sessions and encrypting stored secrets are unrelated jobs, and one
leaked key should not give away both.
"""
from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().credential_key
    if not key:
        raise RuntimeError(
            "credential_key is not configured — set it in config.yaml (generate with: "
            'python3 -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())")'
        )
    return Fernet(key.encode())


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token: Optional[str]) -> str:
    """The stored secret, or "" if there is none or the key no longer opens it."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
