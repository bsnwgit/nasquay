"""
The action catalogue. Everything NASQuay can do is an action with a stable id; every
call to one passes app/actions/gate.py and is written to the audit log.

This module is the source of truth. sync_actions() mirrors it into the actions table
at startup, so the permission grid and the audit log can reference ids.
"""
from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"


@dataclass(frozen=True)
class ActionSpec:
    id: str
    category: str
    classification: str
    description: str
    source: str = "app"
    long_running: bool = False


# ── NASQuay's own actions ─────────────────────────────────────────────────────
APP_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec("users.list",            "users",    READ,        "List NASQuay user accounts"),
    ActionSpec("users.create",          "users",    WRITE,       "Create a NASQuay user account"),
    ActionSpec("users.update",          "users",    WRITE,       "Change a user's name, email, role or enabled state"),
    ActionSpec("users.reset_password",  "users",    WRITE,       "Set another user's password"),
    ActionSpec("users.delete",          "users",    DESTRUCTIVE, "Delete a NASQuay user account"),
    ActionSpec("roles.list",            "roles",    READ,        "List roles, their permissions and the action catalogue"),
    ActionSpec("roles.create",          "roles",    WRITE,       "Create a role"),
    ActionSpec("roles.update",          "roles",    WRITE,       "Rename a role or change its description"),
    ActionSpec("roles.set_permissions", "roles",    WRITE,       "Switch actions on or off for a role"),
    ActionSpec("roles.delete",          "roles",    DESTRUCTIVE, "Delete a role"),
    ActionSpec("audit.read",            "audit",    READ,        "Read the audit log"),
    ActionSpec("settings.read",         "settings", READ,        "Read runtime settings"),
    ActionSpec("settings.update",       "settings", WRITE,       "Change runtime settings"),
    ActionSpec("nas.list",              "nas",      READ,        "List the NAS units NASQuay knows"),
    ActionSpec("nas.create",            "nas",      WRITE,       "Add a NAS, and read the certificate it presents"),
    ActionSpec("nas.update",            "nas",      WRITE,       "Change a NAS's address, credentials or settings"),
    ActionSpec("nas.delete",            "nas",      DESTRUCTIVE, "Remove a NAS from NASQuay"),
    ActionSpec("nas.check",             "nas",      READ,        "Test the connection to a NAS"),
    ActionSpec("tools.list",            "tools",    READ,        "List the tools the NAS units offer"),
    ActionSpec("tools.discover",        "tools",    WRITE,       "Ask a NAS which tools it offers"),
    ActionSpec("tools.review",          "tools",    WRITE,       "Classify a NAS tool and mark it reviewed"),
    ActionSpec("monitoring.read",       "monitoring", READ,      "Read monitoring targets, readings and flags"),
    ActionSpec("monitoring.discover",   "monitoring", WRITE,     "Ask a NAS what there is to watch"),
    ActionSpec("monitoring.update",     "monitoring", WRITE,     "Switch a monitoring target on or off"),
    ActionSpec("monitoring.collect",    "monitoring", READ,      "Take a set of readings now", long_running=True),
    ActionSpec("keys.list",             "keys",     READ,        "List the SSH keys NASQuay connects with, and their public halves"),
    ActionSpec("keys.create",           "keys",     WRITE,       "Generate a new SSH key"),
    ActionSpec("keys.rename",           "keys",     WRITE,       "Rename an SSH key and repoint whatever uses it"),
    ActionSpec("keys.delete",           "keys",     DESTRUCTIVE, "Delete an SSH key"),
    ActionSpec("certificates.list",     "certificates", READ,    "List the certificates NASQuay trusts"),
    ActionSpec("certificates.create",   "certificates", WRITE,   "Upload a certificate for NASQuay to trust"),
    ActionSpec("certificates.delete",   "certificates", DESTRUCTIVE, "Delete an uploaded certificate"),
    ActionSpec("clients.list",          "clients",  READ,        "List the client machines NASQuay watches"),
    ActionSpec("clients.create",        "clients",  WRITE,       "Add a client machine or one of its mounts"),
    ActionSpec("clients.update",        "clients",  WRITE,       "Change a client machine"),
    ActionSpec("clients.delete",        "clients",  DESTRUCTIVE, "Remove a client machine"),
    ActionSpec("clients.check",         "clients",  READ,        "Test the connection to a client machine"),
    ActionSpec("monitoring.backfill",   "monitoring", WRITE,     "Import a NAS's own usage history as a baseline", long_running=True),
    ActionSpec("monitoring.acknowledge", "monitoring", WRITE,    "Acknowledge or clear a flag"),
    ActionSpec("notifications.read",    "notifications", READ,   "See where NASQuay sends word of a flag"),
    ActionSpec("notifications.update",  "notifications", WRITE,  "Change where NASQuay sends word of a flag"),
    ActionSpec("notifications.test",    "notifications", WRITE,  "Send a test notification"),
    ActionSpec("resonance.use",         "resonance", READ,       "Open the embedded assistant"),
    ActionSpec("resonance.read",        "resonance", READ,       "See the assistant's settings"),
    ActionSpec("resonance.update",      "resonance", WRITE,      "Change the assistant's settings"),
    ActionSpec("providers.list",        "providers", READ,       "List the AI providers routines can use"),
    ActionSpec("providers.create",      "providers", WRITE,      "Add an AI provider"),
    ActionSpec("providers.update",      "providers", WRITE,      "Change an AI provider's address, model or key"),
    ActionSpec("providers.delete",      "providers", DESTRUCTIVE, "Remove an AI provider"),
    ActionSpec("providers.test",        "providers", WRITE,      "Send a test request to an AI provider"),
    ActionSpec("system.network_read",  "system",   READ,        "See where NASQuay listens"),
    ActionSpec("system.network_update", "system",   WRITE,       "Change the listen address and port"),
    ActionSpec("system.restart",        "system",   WRITE,       "Restart NASQuay"),
)

ACTIONS: dict[str, ActionSpec] = {a.id: a for a in APP_ACTIONS}


async def sync_actions(db: aiosqlite.Connection) -> None:
    """Mirror the registry into the actions table.

    Existing rows keep their permissions; only metadata that changed in code is
    rewritten, so a restart does not touch every row.
    """
    for a in APP_ACTIONS:
        await db.execute(
            """INSERT INTO actions (id, source, category, classification, description, long_running, reviewed)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                   source         = excluded.source,
                   category       = excluded.category,
                   classification = excluded.classification,
                   description    = excluded.description,
                   long_running   = excluded.long_running,
                   updated_at     = datetime('now')
               WHERE actions.source         IS NOT excluded.source
                  OR actions.category       IS NOT excluded.category
                  OR actions.classification IS NOT excluded.classification
                  OR actions.description    IS NOT excluded.description
                  OR actions.long_running   IS NOT excluded.long_running""",
            (a.id, a.source, a.category, a.classification, a.description, int(a.long_running)),
        )
    await db.commit()
