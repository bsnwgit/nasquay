-- Monitoring: what is watched, what was read, and what that means.
--
-- Readings are deliberately narrow — one row per target, metric and moment — because the
-- rules compare a metric against its own past and against the same metric taken from a
-- different source. Values are integer bytes or counts, never a parsed human-readable
-- figure: `df` and `du` are run with -k and multiplied here.
--
-- Three columns qualify a reading rather than describing it. `cached` marks a figure the
-- NAS computed at some earlier time and hands back unchanged (its per-share file_count
-- does this). `rounded` marks a figure that has lost precision before NASQuay saw it
-- (the usage history does this). `backfilled` marks a reading reconstructed from history
-- rather than taken live. A rule may only use what it is allowed to trust.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS targets (
    id          INTEGER PRIMARY KEY,
    nas_id      INTEGER NOT NULL REFERENCES nas(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('pool', 'volume', 'share', 'client_mount')),
    -- What identifies it on the NAS: a pool id, a volume id, a share name, a mount path.
    ref         TEXT    NOT NULL,
    label       TEXT    NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    first_seen  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (nas_id, kind, ref)
);

CREATE INDEX IF NOT EXISTS idx_targets_nas ON targets(nas_id, enabled);

CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY,
    taken_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    target_id   INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    metric      TEXT    NOT NULL,
    value       INTEGER,
    source      TEXT    NOT NULL CHECK (source IN ('mcp', 'ssh', 'client')),
    rounded     INTEGER NOT NULL DEFAULT 0 CHECK (rounded IN (0, 1)),
    cached      INTEGER NOT NULL DEFAULT 0 CHECK (cached IN (0, 1)),
    backfilled  INTEGER NOT NULL DEFAULT 0 CHECK (backfilled IN (0, 1)),
    -- What the NAS actually said, kept so a disputed reading can be re-read later.
    raw         TEXT    NOT NULL DEFAULT ''
);

-- The shape every rule and every chart reads in: one metric on one target over time.
CREATE INDEX IF NOT EXISTS idx_readings_series ON readings(target_id, metric, taken_at DESC);
CREATE INDEX IF NOT EXISTS idx_readings_taken ON readings(taken_at);

-- A rule that fired. Flags are not deleted when the condition passes: they are cleared,
-- so the record of what was seen survives.
CREATE TABLE IF NOT EXISTS flags (
    id           INTEGER PRIMARY KEY,
    raised_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    rule         TEXT    NOT NULL,
    target_id    INTEGER REFERENCES targets(id) ON DELETE CASCADE,
    nas_id       INTEGER REFERENCES nas(id) ON DELETE CASCADE,
    severity     TEXT    NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'error')),
    detail       TEXT    NOT NULL DEFAULT '',
    value        INTEGER,
    previous     INTEGER,
    cleared_at   TEXT,
    acknowledged_at TEXT,
    acknowledged_by TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_flags_open ON flags(cleared_at, raised_at DESC);

-- One row per collection run. `worker_stale` is a rule about this table, which is why the
-- worker records its runs rather than merely logging them.
CREATE TABLE IF NOT EXISTS collection_runs (
    id           INTEGER PRIMARY KEY,
    tier         TEXT    NOT NULL CHECK (tier IN ('fast', 'slow', 'manual')),
    started_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    readings     INTEGER NOT NULL DEFAULT 0,
    detail       TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_tier ON collection_runs(tier, started_at DESC);
