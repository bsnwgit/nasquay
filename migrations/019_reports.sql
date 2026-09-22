-- Reports: what has been happening, read when nobody is alarmed.
--
-- A report is built only from what NASQuay already recorded — readings, flags, runs and
-- the audit log — so producing one never contacts a NAS and can be repeated at will.
--
-- Each run keeps its figures as JSON rather than a rendered file. The page, the CSV and
-- the PDF are all made from those figures on demand, so a report that was produced once
-- can be re-read in any of the three, and nothing on disk has to be kept in step.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS reports (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL UNIQUE COLLATE NOCASE
                              CHECK (length(name) BETWEEN 1 AND 64),
    description       TEXT    NOT NULL DEFAULT '',
    kind              TEXT    NOT NULL
                              CHECK (kind IN ('capacity', 'change', 'health', 'activity')),
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    -- How far back the report looks.
    period_days       INTEGER NOT NULL DEFAULT 30 CHECK (period_days BETWEEN 1 AND 3650),
    -- One NAS, or every one NASQuay knows.
    nas_id            INTEGER REFERENCES nas(id) ON DELETE CASCADE,

    -- The same schedule kinds as a routine, in the installation's time zone.
    schedule_kind     TEXT    NOT NULL DEFAULT 'manual'
                              CHECK (schedule_kind IN ('manual', 'interval', 'daily', 'weekly')),
    interval_minutes  INTEGER NOT NULL DEFAULT 1440 CHECK (interval_minutes BETWEEN 5 AND 10080),
    at_time           TEXT    NOT NULL DEFAULT '07:00',
    weekday           INTEGER NOT NULL DEFAULT 0 CHECK (weekday BETWEEN 0 AND 6),
    schedule_from     TEXT    NOT NULL DEFAULT (datetime('now')),

    -- A report shows what this user's role may see, and never more.
    run_as_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- Whether a finished report is sent on the notification channels. What is sent —
    -- the document, a link, or both — is the report_delivery setting.
    deliver           INTEGER NOT NULL DEFAULT 0 CHECK (deliver IN (0, 1)),

    -- An optional summary in words, over the report's own figures. Marked as written by
    -- a model wherever it is shown, and never in place of the figures.
    ai_summary        INTEGER NOT NULL DEFAULT 0 CHECK (ai_summary IN (0, 1)),
    provider_id       INTEGER REFERENCES ai_providers(id) ON DELETE SET NULL,

    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by        INTEGER,
    updated_at        TEXT,
    updated_by        INTEGER
);

CREATE TABLE IF NOT EXISTS report_runs (
    id           INTEGER PRIMARY KEY,
    report_id    INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    trigger      TEXT    NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    requested_by INTEGER,
    status       TEXT    NOT NULL CHECK (status IN ('queued', 'running', 'ok', 'error')),
    queued_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    -- The report itself: sections, each with rows and columns, as JSON.
    figures      TEXT    NOT NULL DEFAULT '{}',
    summary      TEXT    NOT NULL DEFAULT '',   -- written by a model, when asked for
    error        TEXT    NOT NULL DEFAULT '',
    delivered    TEXT    NOT NULL DEFAULT ''    -- what the delivery did, if one was asked for
);

CREATE INDEX IF NOT EXISTS idx_report_runs_report ON report_runs(report_id, id);
CREATE INDEX IF NOT EXISTS idx_report_runs_status ON report_runs(status);
