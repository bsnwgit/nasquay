-- Which volume a share lives on.
--
-- `df` needs a path, and QNAP's /share/<name> is a symlink onto the volume holding that
-- share — so a volume's `df` reading is taken through one of its own shares. Without this
-- column the collector had no way to tell which share belonged to which volume, and every
-- volume on a NAS was measured through the same one.
--
-- Readings taken before this are unreliable for volumes and are removed below; the other
-- metrics are unaffected.

PRAGMA foreign_keys = ON;

ALTER TABLE targets ADD COLUMN parent_ref TEXT NOT NULL DEFAULT '';

DELETE FROM readings
WHERE metric LIKE 'df_%'
  AND target_id IN (SELECT id FROM targets WHERE kind = 'volume');
