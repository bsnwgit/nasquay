-- A link to each NAS's own administration interface.
--
-- Its own field rather than something derived from `address` and `mcp_port`: that pair is
-- where MCP Assistant answers, which is not where the NAS is administered, and a NAS may
-- sit behind a proxy, on another port, or answer to a name NASQuay never uses.
--
-- Presentation only. Following the link leaves NASQuay; nothing here is fetched, checked
-- or proxied by the app.

PRAGMA foreign_keys = ON;

ALTER TABLE nas ADD COLUMN admin_url TEXT NOT NULL DEFAULT '';
