"""
Who is calling. Every permission check and every audit record is about a Caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Caller:
    kind: str                      # user | api_token | routine | system | anonymous
    via: str                       # web | resonance | mcp | routine | worker | install
    username: str
    user_id: Optional[int] = None
    role_id: Optional[int] = None
    role_name: str = ""
    is_admin: bool = False
    client_ip: str = ""
