-- NASQuay initial schema: users, roles, the action catalogue, per-role permissions,
-- the audit log and runtime settings.
--
-- Applied once by app/database.py, which records it in _migrations.

PRAGMA foreign_keys = ON;

-- ── Roles ─────────────────────────────────────────────────────────────────────
-- Only the built-in admin role may carry is_admin. It holds every permission
-- implicitly, so it never needs rows in role_permissions and cannot be locked out
-- by an edit to the permission grid.
CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE
                        CHECK (length(name) BETWEEN 1 AND 64),
    description TEXT    NOT NULL DEFAULT '',
    is_builtin  INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0, 1)),
    is_admin    INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT
);

INSERT OR IGNORE INTO roles (id, name, description, is_builtin, is_admin)
VALUES (1, 'Admin', 'Full control of NASQuay. Holds every permission and cannot be edited.', 1, 1);

CREATE TRIGGER IF NOT EXISTS roles_admin_flag_builtin_only_insert
BEFORE INSERT ON roles
WHEN NEW.is_admin = 1 AND NEW.is_builtin = 0
BEGIN
    SELECT RAISE(ABORT, 'admin_flag_builtin_only');
END;

CREATE TRIGGER IF NOT EXISTS roles_builtin_locked_update
BEFORE UPDATE OF name, is_admin, is_builtin ON roles
WHEN OLD.is_builtin = 1 OR NEW.is_admin = 1 OR NEW.is_builtin = 1
BEGIN
    SELECT RAISE(ABORT, 'builtin_role_locked');
END;

CREATE TRIGGER IF NOT EXISTS roles_builtin_locked_delete
BEFORE DELETE ON roles
WHEN OLD.is_builtin = 1
BEGIN
    SELECT RAISE(ABORT, 'builtin_role_locked');
END;

-- ── Users ─────────────────────────────────────────────────────────────────────
-- token_version is embedded in issued tokens; bumping it (password change,
-- disable, role change) invalidates every session for that user at once.
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT    NOT NULL UNIQUE COLLATE NOCASE
                            CHECK (length(username) BETWEEN 1 AND 64),
    display_name    TEXT    NOT NULL DEFAULT '',
    email           TEXT    NOT NULL DEFAULT '',
    hashed_password TEXT,
    role_id         INTEGER NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    token_version   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT,
    last_login      TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role_id);

-- The last-admin rule is enforced by the API, and again here, so no code path —
-- a bug, a script, a hand-run statement — can leave the app with no enabled admin.
CREATE TRIGGER IF NOT EXISTS users_keep_an_admin_update
BEFORE UPDATE OF is_active, role_id ON users
WHEN OLD.is_active = 1
 AND (SELECT is_admin FROM roles WHERE id = OLD.role_id) = 1
 AND (NEW.is_active = 0 OR (SELECT is_admin FROM roles WHERE id = NEW.role_id) = 0)
 AND (SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
      WHERE u.is_active = 1 AND r.is_admin = 1 AND u.id != OLD.id) = 0
BEGIN
    SELECT RAISE(ABORT, 'last_admin');
END;

CREATE TRIGGER IF NOT EXISTS users_keep_an_admin_delete
BEFORE DELETE ON users
WHEN OLD.is_active = 1
 AND (SELECT is_admin FROM roles WHERE id = OLD.role_id) = 1
 AND (SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
      WHERE u.is_active = 1 AND r.is_admin = 1 AND u.id != OLD.id) = 0
BEGIN
    SELECT RAISE(ABORT, 'last_admin');
END;

-- ── Action catalogue ──────────────────────────────────────────────────────────
-- The registry in app/actions/ is the source of truth; it is synced into this
-- table at startup so the permission grid and the audit log can reference ids.
-- classification is NASQuay's own — never taken from a NAS's tool annotations.
CREATE TABLE IF NOT EXISTS actions (
    id             TEXT    PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
    source         TEXT    NOT NULL CHECK (source IN ('app', 'qnap_mcp', 'ssh')),
    category       TEXT    NOT NULL,
    classification TEXT    NOT NULL CHECK (classification IN ('read', 'write', 'destructive')),
    description    TEXT    NOT NULL DEFAULT '',
    long_running   INTEGER NOT NULL DEFAULT 0 CHECK (long_running IN (0, 1)),
    reviewed       INTEGER NOT NULL DEFAULT 1 CHECK (reviewed IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT
);

-- ── Permissions ───────────────────────────────────────────────────────────────
-- One switch per role per action. No row means not allowed, so an action added
-- later starts switched off for every role except admin. Per-NAS overrides
-- arrive with the NAS table in a later migration.
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id    INTEGER NOT NULL REFERENCES roles(id)   ON DELETE CASCADE,
    action_id  TEXT    NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    allowed    INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_by INTEGER,
    PRIMARY KEY (role_id, action_id)
);

-- ── Audit log ─────────────────────────────────────────────────────────────────
-- Deliberately no foreign keys: a record must outlive the user, action or NAS
-- it names. actor_name is copied at write time for the same reason.
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY,
    at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    actor_kind  TEXT    NOT NULL CHECK (actor_kind IN ('user', 'api_token', 'routine', 'system', 'anonymous')),
    actor_id    INTEGER,
    actor_name  TEXT    NOT NULL DEFAULT '',
    via         TEXT    NOT NULL CHECK (via IN ('web', 'resonance', 'mcp', 'routine', 'worker', 'install')),
    action_id   TEXT    NOT NULL,
    nas_id      INTEGER,
    target      TEXT    NOT NULL DEFAULT '',
    params      TEXT    NOT NULL DEFAULT '{}',
    decision    TEXT    NOT NULL CHECK (decision IN ('allowed', 'denied')),
    reason      TEXT    NOT NULL DEFAULT '',
    outcome     TEXT             CHECK (outcome IN ('ok', 'error')),
    detail      TEXT    NOT NULL DEFAULT '',
    duration_ms INTEGER,
    job_id      INTEGER,
    client_ip   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_at     ON audit(at);
CREATE INDEX IF NOT EXISTS idx_audit_actor  ON audit(actor_kind, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action_id);

-- ── Runtime settings ──────────────────────────────────────────────────────────
-- Values are JSON. Defaults live in code, so a missing key means "default".
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 128),
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by INTEGER
);
