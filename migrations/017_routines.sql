-- Routines: work that runs on a schedule, as a chosen user, with nobody watching.
--
-- A routine never does more than its run-as user's role allows, and never more than its
-- own list of operations. Destructive operations stay out unless the routine says so,
-- because an unattended caller has nobody to confirm with.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS routines (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL UNIQUE COLLATE NOCASE
                              CHECK (length(name) BETWEEN 1 AND 64),
    description       TEXT    NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    -- fixed: an ordered list of steps, no AI. ai: a prompt, a provider, and the
    -- operations the model may call.
    kind              TEXT    NOT NULL CHECK (kind IN ('fixed', 'ai')),
    -- SET NULL rather than RESTRICT: removing a user must not be blocked by a routine
    -- somebody forgot. A routine with nobody to run as refuses to run, and says why.
    run_as_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- manual: only when somebody presses Run. The rest are what they say, in the
    -- installation's time zone.
    schedule_kind     TEXT    NOT NULL DEFAULT 'manual'
                              CHECK (schedule_kind IN ('manual', 'interval', 'daily', 'weekly')),
    interval_minutes  INTEGER NOT NULL DEFAULT 60 CHECK (interval_minutes BETWEEN 5 AND 10080),
    at_time           TEXT    NOT NULL DEFAULT '07:00',
    weekday           INTEGER NOT NULL DEFAULT 0 CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
    -- When the schedule last changed. A slot before this is never run, so saving a
    -- daily 07:00 routine at 09:00 does not fire it at once for a morning already past.
    schedule_from     TEXT    NOT NULL DEFAULT (datetime('now')),

    provider_id       INTEGER REFERENCES ai_providers(id) ON DELETE SET NULL,
    prompt            TEXT    NOT NULL DEFAULT '',
    steps             TEXT    NOT NULL DEFAULT '[]',   -- fixed: JSON list of steps
    allowed           TEXT    NOT NULL DEFAULT '[]',   -- ai: JSON list of operation ids
    allow_destructive INTEGER NOT NULL DEFAULT 0 CHECK (allow_destructive IN (0, 1)),
    max_steps         INTEGER NOT NULL DEFAULT 8 CHECK (max_steps BETWEEN 1 AND 30),
    timeout_s         INTEGER NOT NULL DEFAULT 600 CHECK (timeout_s BETWEEN 30 AND 3600),
    alert_on          TEXT    NOT NULL DEFAULT 'failure'
                              CHECK (alert_on IN ('never', 'failure', 'always')),

    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by        INTEGER,
    updated_at        TEXT,
    updated_by        INTEGER
);

CREATE TABLE IF NOT EXISTS routine_runs (
    id           INTEGER PRIMARY KEY,
    routine_id   INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    trigger      TEXT    NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    requested_by INTEGER,
    status       TEXT    NOT NULL CHECK (status IN ('queued', 'running', 'ok', 'error')),
    queued_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    output       TEXT    NOT NULL DEFAULT '',
    error        TEXT    NOT NULL DEFAULT '',
    calls        TEXT    NOT NULL DEFAULT '[]',   -- JSON: each operation called, and how it ended
    alert        TEXT    NOT NULL DEFAULT ''      -- what the alert did, if one was sent
);

CREATE INDEX IF NOT EXISTS idx_routine_runs_routine ON routine_runs(routine_id, id);
CREATE INDEX IF NOT EXISTS idx_routine_runs_status  ON routine_runs(status);

-- What each NAS tool takes, as the NAS described it, so a model can be told how to call
-- it. Filled in by discovery; a tool discovered before this column existed has '{}'
-- until the NAS is discovered again.
ALTER TABLE nas_tools ADD COLUMN input_schema TEXT NOT NULL DEFAULT '{}';
ALTER TABLE nas_tools ADD COLUMN tool_description TEXT NOT NULL DEFAULT '';
