-- Certificates an administrator has uploaded, and the one a NAS is verified against.
--
-- Pinning a fingerprint stays the default and needs nothing stored here. This is the
-- other half of that decision: where a NAS presents a certificate from an organisation's
-- own authority, the authority is uploaded once and every NAS it issued for is verified
-- against it properly, chain and name, rather than pinned leaf by leaf.
--
-- A certificate is public by nature — there is no private key here, and nothing in this
-- table is a credential.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS certificates (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE
                        CHECK (length(name) BETWEEN 1 AND 64),
    pem         TEXT    NOT NULL,
    fingerprint TEXT    NOT NULL,          -- sha256 of the DER, lower case hex
    subject     TEXT    NOT NULL DEFAULT '',
    issuer      TEXT    NOT NULL DEFAULT '',
    not_before  TEXT    NOT NULL DEFAULT '',
    not_after   TEXT    NOT NULL DEFAULT '',
    is_ca       INTEGER NOT NULL DEFAULT 0 CHECK (is_ca IN (0, 1)),
    added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    added_by    INTEGER
);

-- Which certificate a NAS is verified against, when it is not pinned. NULL means the
-- host's own trust store. ON DELETE SET NULL cannot be added by ALTER TABLE, so removal
-- is refused in the API while a NAS still names the certificate.
ALTER TABLE nas ADD COLUMN tls_cert_id INTEGER REFERENCES certificates(id);
