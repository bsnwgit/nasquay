-- Machines that mount a NAS share, and the mounts themselves.
--
-- The NAS's own view of a share is not the only one that matters: what a client sees is
-- what the people using it see. A mount that has quietly dropped, or a client reporting a
-- different size from the NAS, is invisible from the NAS side — and dropped mounts have
-- already happened here.
--
-- A client is reached over SSH with NASQuay's own key, exactly as a NAS is, and only the
-- same fixed read-only commands are ever run on it.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL UNIQUE,
    address           TEXT    NOT NULL,
    ssh_user          TEXT    NOT NULL,
    ssh_port          INTEGER NOT NULL DEFAULT 22,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_checked_at   TEXT,
    last_check_ok     INTEGER,
    last_check_detail TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT
);

-- A client_mount target is a path on a client that should hold a particular share:
--   client_id  which machine to ask
--   ref        the path on that machine
--   parent_ref the share it is supposed to be
ALTER TABLE targets ADD COLUMN client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE;
