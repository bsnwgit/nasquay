-- Slack as a third notification channel.
--
-- An incoming webhook URL is a credential in its own right — anyone holding it can post
-- to that channel — so it is encrypted and never returned, exactly like the mail password
-- and the ntfy token.

PRAGMA foreign_keys = ON;

ALTER TABLE notifications ADD COLUMN slack_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (slack_enabled IN (0, 1));
ALTER TABLE notifications ADD COLUMN slack_webhook TEXT NOT NULL DEFAULT '';   -- encrypted
