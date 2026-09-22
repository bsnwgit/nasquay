-- Comparing a report's period with the one before it.
--
-- "Series-B grew 2 TiB this month" is a figure. "It grew 2 TiB this month against 400 GiB
-- last month" is the thing somebody acts on, and it needs no new readings — only the same
-- arithmetic run over the period before.

PRAGMA foreign_keys = ON;

ALTER TABLE reports ADD COLUMN compare INTEGER NOT NULL DEFAULT 0 CHECK (compare IN (0, 1));
