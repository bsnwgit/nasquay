-- NAS units, their credentials, and per-NAS permission overrides.
--
-- The MCP token is stored encrypted (Fernet, app/crypto.py) and never returned by the
-- API. SSH uses the host's own key, so only the account and port live here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nas (
    id                  INTEGER PRIMARY KEY,
    name                TEXT    NOT NULL UNIQUE COLLATE NOCASE
                                CHECK (length(name) BETWEEN 1 AND 64),
    address             TEXT    NOT NULL CHECK (length(address) BETWEEN 1 AND 255),
    mcp_port            INTEGER NOT NULL DEFAULT 8443 CHECK (mcp_port BETWEEN 1 AND 65535),
    -- how the MCP server's certificate is trusted: pinned fingerprint, or the system's
    -- own trust store. It is never simply ignored.
    tls_mode            TEXT    NOT NULL DEFAULT 'pinned' CHECK (tls_mode IN ('pinned', 'system')),
    tls_fingerprint     TEXT    NOT NULL DEFAULT '',
    mcp_token           TEXT    NOT NULL DEFAULT '',   -- Fernet ciphertext
    ssh_user            TEXT    NOT NULL DEFAULT '',
    ssh_port            INTEGER NOT NULL DEFAULT 22 CHECK (ssh_port BETWEEN 1 AND 65535),
    enabled             INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_checked_at     TEXT,
    last_check_ok       INTEGER,
    last_check_detail   TEXT    NOT NULL DEFAULT '',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT
);

-- Per-NAS overrides of a role's permissions. A row here wins over role_permissions for
-- that NAS; no row means the role's general setting applies.
CREATE TABLE IF NOT EXISTS role_nas_permissions (
    role_id    INTEGER NOT NULL REFERENCES roles(id)   ON DELETE CASCADE,
    action_id  TEXT    NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    nas_id     INTEGER NOT NULL REFERENCES nas(id)     ON DELETE CASCADE,
    allowed    INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_by INTEGER,
    PRIMARY KEY (role_id, action_id, nas_id)
);

CREATE INDEX IF NOT EXISTS idx_role_nas_permissions_nas ON role_nas_permissions(nas_id);
