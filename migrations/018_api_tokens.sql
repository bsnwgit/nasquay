-- Personal API tokens, for outside AI tools that reach NASQuay over MCP.
--
-- A token acts as its owner and never more: the owner's role decides every call, and the
-- token can narrow that further — read-only unless it says otherwise, and never
-- destructive unless an administrator allowed it. Only a SHA-256 hash is kept; the token
-- itself is shown once, when it is made, and cannot be recovered.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS api_tokens (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name              TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    token_hash        TEXT    NOT NULL UNIQUE,     -- sha256 of the token, hex
    prefix            TEXT    NOT NULL,            -- the first characters, to tell tokens apart
    -- read: only operations that change nothing. write: reads and writes.
    access            TEXT    NOT NULL DEFAULT 'read' CHECK (access IN ('read', 'write')),
    allow_destructive INTEGER NOT NULL DEFAULT 0 CHECK (allow_destructive IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by        INTEGER,
    expires_at        TEXT,                        -- NULL: never
    last_used_at      TEXT,
    revoked_at        TEXT,
    revoked_by        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
