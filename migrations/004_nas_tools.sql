-- Which MCP tools each NAS offers.
--
-- The tools themselves become rows in `actions` (id `qnap.<tool>`, source qnap_mcp), so a
-- role switches them on or off exactly like NASQuay's own actions. This table records
-- which NAS offers which, since firmware and app versions differ between boxes.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nas_tools (
    nas_id      INTEGER NOT NULL REFERENCES nas(id)     ON DELETE CASCADE,
    action_id   TEXT    NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    tool_name   TEXT    NOT NULL,
    available   INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
    first_seen  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (nas_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_nas_tools_action ON nas_tools(action_id);
