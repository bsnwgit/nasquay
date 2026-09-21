-- The embedded assistant's settings.
--
-- One row, like notifications, and for the same reason: the embed key is a secret, and
-- the settings endpoint hands back everything it holds. The key follows the rule every
-- other secret here follows — written, never returned, encrypted at rest.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS resonance (
    id           INTEGER PRIMARY KEY CHECK (id = 1),

    enabled      INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    -- The embed server's address, as a browser would reach it: the assistant is framed
    -- by the person's browser, not fetched by this host, so a name only this host can
    -- resolve is no use. NASQuay calls it too, to mint each session code.
    base_url     TEXT    NOT NULL DEFAULT '',
    embed_key    TEXT    NOT NULL DEFAULT '',   -- encrypted
    -- What the launcher says, and which corner it sits in.
    label        TEXT    NOT NULL DEFAULT 'Assistant',
    side         TEXT    NOT NULL DEFAULT 'right' CHECK (side IN ('left', 'right')),
    -- A CA bundle for an internal authority, when the embed server's certificate is not
    -- signed by one this host already trusts. The browser's trust is a separate matter:
    -- it must trust the certificate too, or the frame fails silently.
    ca_bundle    TEXT    NOT NULL DEFAULT '',

    last_used_at TEXT,
    last_result  TEXT    NOT NULL DEFAULT '',
    updated_at   TEXT,
    updated_by   INTEGER
);

INSERT OR IGNORE INTO resonance (id) VALUES (1);
