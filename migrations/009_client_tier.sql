-- Client mounts collect on their own schedule.
--
-- They were read as part of the fast pass, which tied how often a mount is checked to how
-- often a NAS is polled. They are different questions with different costs: one SSH call to
-- a client is cheap, and whether a share is still mounted is worth asking more often than
-- whether a volume's free space moved.
--
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt.

PRAGMA foreign_keys = OFF;

CREATE TABLE collection_runs_new (
    id           INTEGER PRIMARY KEY,
    tier         TEXT    NOT NULL CHECK (tier IN ('fast', 'slow', 'client', 'manual')),
    started_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    readings     INTEGER NOT NULL DEFAULT 0,
    detail       TEXT    NOT NULL DEFAULT ''
);

INSERT INTO collection_runs_new (id, tier, started_at, finished_at, status, readings, detail)
    SELECT id, tier, started_at, finished_at, status, readings, detail FROM collection_runs;

DROP TABLE collection_runs;
ALTER TABLE collection_runs_new RENAME TO collection_runs;

CREATE INDEX IF NOT EXISTS idx_collection_runs_tier ON collection_runs(tier, started_at DESC);

PRAGMA foreign_keys = ON;
