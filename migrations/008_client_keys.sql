-- Which key a client is reached with.
--
-- Empty means the install's own key, the one install.sh made and the NAS units already
-- trust. A client can be given its own instead, so authorising NASQuay on somebody's
-- workstation does not hand it the key the NAS units accept.

PRAGMA foreign_keys = ON;

ALTER TABLE clients ADD COLUMN key_name TEXT NOT NULL DEFAULT '';
