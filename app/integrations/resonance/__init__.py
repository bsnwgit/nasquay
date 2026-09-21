"""
Resonance embed integration — the assistant panel, inside NASQuay.

Vendored rather than depended on: install.sh builds a venv from requirements.txt on
someone else's host, and a private index would put a credentialed network dependency in
the middle of every install.

How the pieces fit:

  browser                 NASQuay                      resonance
  ───────                 ───────                      ─────────
  mount ───GET──────▶  /api/resonance/code  ──POST──▶  /embed/session
        ◀──code──────                       ◀──code───
  iframe ─────────────────────────────────────────────▶  /embed?c=<code>

NASQuay's key never reaches the browser, and resonance never sees a NASQuay password —
NASQuay vouches for the signed-in person and gets back a short-lived, single-use code.

NASQuay writes its own mount rather than using resonance's loader, which is what the
embed contract asks of an application whose session is a token in memory: the loader
expects the code endpoint to authenticate by cookie, and NASQuay's refresh cookie is
deliberately scoped to /api/auth and goes nowhere else.
"""
from __future__ import annotations

# Bump when the wire contract or the endpoint shape changes, so an install running an
# older copy is identifiable from its settings page rather than by inspection.
RESONANCE_MODULE_VERSION = "1.0.0"

# Prefixed onto the user id sent to resonance ("nasquay-robert"), so its own records show
# both who and which application. A constant rather than a setting on purpose: an
# administrator must not be able to make their install report itself as something else.
APP_SLUG = "nasquay"

__all__ = ["RESONANCE_MODULE_VERSION", "APP_SLUG"]
