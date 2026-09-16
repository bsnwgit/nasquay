"""
NASQuay startup configuration.

Priority order (highest → lowest):
  1. Environment variables (NASQUAY_*)
  2. config.yaml — $NASQUAY_CONFIG, $NASQUAY_INSTALL_DIR, the working directory,
     /opt/nasquay or ~/.nasquay
  3. Defaults defined here

Only settings needed before the database opens belong here. Runtime settings live in
SQLite and are read through app/settings_store.py.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def config_candidates() -> list[Path]:
    candidates = [
        Path("config.yaml"),
        Path("/opt/nasquay/config.yaml"),
        Path.home() / ".nasquay" / "config.yaml",
    ]
    install_dir = os.environ.get("NASQUAY_INSTALL_DIR")
    if install_dir:
        candidates.insert(0, Path(install_dir) / "config.yaml")
    explicit = os.environ.get("NASQUAY_CONFIG")
    if explicit:
        candidates.insert(0, Path(explicit))
    return candidates


def _load_yaml() -> dict:
    """Return the first config.yaml found, parsed, or {}."""
    for path in config_candidates():
        if path.is_file():
            with path.open() as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise RuntimeError(f"{path} must contain a YAML mapping")
            return data
    return {}


_yaml_cfg = _load_yaml()
_INSTALL_DIR = Path(
    os.environ.get("NASQUAY_INSTALL_DIR") or _yaml_cfg.get("install_dir") or Path.cwd()
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NASQUAY_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = Field(default=_yaml_cfg.get("host", "127.0.0.1"))
    port: int = Field(default=_yaml_cfg.get("port", 8770), ge=1, le=65535)
    public_url: str = Field(default=_yaml_cfg.get("public_url", ""))
    log_level: Literal["critical", "error", "warning", "info", "debug"] = Field(
        default=_yaml_cfg.get("log_level", "info")
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    install_dir: str = Field(default=str(_INSTALL_DIR))
    db_path: str = Field(default=_yaml_cfg.get("db_path", str(_INSTALL_DIR / "data" / "nasquay.db")))
    secrets_dir: str = Field(default=_yaml_cfg.get("secrets_dir", str(_INSTALL_DIR / "secrets")))
    # The key NASQuay uses to reach a NAS over SSH. Its public half is authorised on each
    # NAS; the private half never leaves this host.
    ssh_key_path: str = Field(
        default=_yaml_cfg.get("ssh_key_path", str(_INSTALL_DIR / "secrets" / "id_ed25519"))
    )

    # ── Sessions ──────────────────────────────────────────────────────────────
    secret_key: str = Field(default=_yaml_cfg.get("secret_key", ""))
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(
        default=_yaml_cfg.get("access_token_expire_minutes", 15), ge=1, le=240
    )
    refresh_token_expire_days: int = Field(
        default=_yaml_cfg.get("refresh_token_expire_days", 7), ge=1, le=90
    )

    # ── Stored-secret encryption (Fernet) ─────────────────────────────────────
    # Separate from secret_key: signing sessions and encrypting stored secrets are
    # unrelated jobs, and one leaked key should not give away both.
    credential_key: str = Field(default=_yaml_cfg.get("credential_key", ""))


# Placeholders from config.example.yaml. A copy of that file with the keys left
# unedited would otherwise sign sessions with a key anyone can read.
_INSECURE_SECRET_KEYS = {"", "CHANGE_ME_generate_with_openssl_rand_hex_32"}
_INSECURE_CREDENTIAL_KEYS = {"", "CHANGE_ME_generate_with_fernet_generate_key"}


def _validate_secrets(s: Settings) -> None:
    """Fail loudly at startup rather than run with a missing or publicly known key."""
    secret_key = (s.secret_key or "").strip()
    if secret_key in _INSECURE_SECRET_KEYS or len(secret_key) < 32:
        raise RuntimeError(
            "NASQuay refuses to start: secret_key is missing, too short, or still the "
            "placeholder from config.example.yaml. Set a unique value of at least 32 "
            "characters in config.yaml — `openssl rand -hex 32` generates one."
        )
    if (s.credential_key or "").strip() in _INSECURE_CREDENTIAL_KEYS:
        raise RuntimeError(
            "NASQuay refuses to start: credential_key is missing or still the placeholder "
            "from config.example.yaml. Generate one with: python3 -c \"from "
            "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    _validate_secrets(s)
    return s
