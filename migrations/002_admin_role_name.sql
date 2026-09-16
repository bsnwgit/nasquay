-- Display the built-in admin role as "Admin".
--
-- It cannot be edited in the app, so its stored name is what everyone sees — role menus,
-- the audit log, the signed-in user's role. The trigger that protects built-in roles
-- refuses a rename, so it is dropped and recreated unchanged around this one update.

PRAGMA foreign_keys = ON;

DROP TRIGGER IF EXISTS roles_builtin_locked_update;

UPDATE roles
   SET name = 'Admin', updated_at = datetime('now')
 WHERE is_builtin = 1 AND name = 'admin';

CREATE TRIGGER IF NOT EXISTS roles_builtin_locked_update
BEFORE UPDATE OF name, is_admin, is_builtin ON roles
WHEN OLD.is_builtin = 1 OR NEW.is_admin = 1 OR NEW.is_builtin = 1
BEGIN
    SELECT RAISE(ABORT, 'builtin_role_locked');
END;
