-- What an administrator has chosen not to show, per NAS.
--
-- Presentation, not permission. Hiding a share or a folder keeps it out of the listings
-- this application draws; it grants nothing, withholds nothing, and a role that may not
-- read a share still cannot, shown or not. The NAS is unchanged either way.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS hidden_items (
    id       INTEGER PRIMARY KEY,
    nas_id   INTEGER NOT NULL REFERENCES nas(id) ON DELETE CASCADE,
    -- 'share' is a shared folder by name; 'path' is one folder at one place in the tree,
    -- as File Station spells it (/Series-B/@Recycle).
    kind     TEXT    NOT NULL CHECK (kind IN ('share', 'path')),
    value    TEXT    NOT NULL CHECK (length(value) BETWEEN 1 AND 1024),
    added_at TEXT    NOT NULL DEFAULT (datetime('now')),
    added_by INTEGER
);

-- NOCASE because QTS treats these names case-insensitively, and hiding "Series-B" twice
-- under two spellings would be two rows that behave as one.
CREATE UNIQUE INDEX IF NOT EXISTS idx_hidden_items_unique
    ON hidden_items(nas_id, kind, value COLLATE NOCASE);
