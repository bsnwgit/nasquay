-- Where to send word when something is flagged.
--
-- One row, because these are the app's own settings rather than a list of things. Kept
-- out of the settings table because two of the fields are secrets: the settings endpoint
-- hands back everything it holds, and a password has no business being in that answer.
-- These follow the same rule as a NAS token — written, never returned, encrypted at rest.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS notifications (
    id                INTEGER PRIMARY KEY CHECK (id = 1),

    -- What is worth waking somebody for. Warnings are off by default: a divergence of a
    -- few percent is worth seeing on a page, not at three in the morning.
    on_error          INTEGER NOT NULL DEFAULT 1 CHECK (on_error IN (0, 1)),
    on_warning        INTEGER NOT NULL DEFAULT 0 CHECK (on_warning IN (0, 1)),
    on_cleared        INTEGER NOT NULL DEFAULT 1 CHECK (on_cleared IN (0, 1)),

    email_enabled     INTEGER NOT NULL DEFAULT 0 CHECK (email_enabled IN (0, 1)),
    smtp_host         TEXT    NOT NULL DEFAULT '',
    smtp_port         INTEGER NOT NULL DEFAULT 587,
    smtp_security     TEXT    NOT NULL DEFAULT 'starttls'
                      CHECK (smtp_security IN ('none', 'starttls', 'tls')),
    smtp_user         TEXT    NOT NULL DEFAULT '',
    smtp_password     TEXT    NOT NULL DEFAULT '',   -- encrypted
    mail_from         TEXT    NOT NULL DEFAULT '',
    mail_to           TEXT    NOT NULL DEFAULT '',

    ntfy_enabled      INTEGER NOT NULL DEFAULT 0 CHECK (ntfy_enabled IN (0, 1)),
    ntfy_server       TEXT    NOT NULL DEFAULT 'https://ntfy.sh',
    ntfy_topic        TEXT    NOT NULL DEFAULT '',
    ntfy_token        TEXT    NOT NULL DEFAULT '',   -- encrypted

    last_sent_at      TEXT,
    last_result       TEXT    NOT NULL DEFAULT '',
    updated_at        TEXT
);

INSERT OR IGNORE INTO notifications (id) VALUES (1);
