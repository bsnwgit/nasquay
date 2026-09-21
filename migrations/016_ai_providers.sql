-- The AI services routines can be run against.
--
-- Any number, because a small local model and a large outside one are good at different
-- work, and a routine names the one it wants. The API key follows the rule every other
-- secret here follows — written, never returned, encrypted at rest.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ai_providers (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL UNIQUE COLLATE NOCASE
                           CHECK (length(name) BETWEEN 1 AND 64),
    -- openai covers anything that speaks the OpenAI chat API: Ollama, LM Studio, vLLM,
    -- OpenAI itself. anthropic is the Anthropic Messages API.
    kind           TEXT    NOT NULL CHECK (kind IN ('openai', 'anthropic')),
    base_url       TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    api_key        TEXT    NOT NULL DEFAULT '',   -- encrypted; a local server may need none
    -- Generous by default: a small model on modest hardware can take most of a minute to
    -- answer a prompt that carries a list of tools.
    timeout_s      INTEGER NOT NULL DEFAULT 120 CHECK (timeout_s BETWEEN 5 AND 900),
    -- What the administrator says. The test records what the model actually did, in
    -- tools_ok, and a routine that needs tools is refused a provider that failed it.
    supports_tools INTEGER NOT NULL DEFAULT 1 CHECK (supports_tools IN (0, 1)),
    enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    -- An uploaded certificate to verify the server against, for one issued by an
    -- internal authority. NULL means the host's own trust store.
    tls_cert_id    INTEGER REFERENCES certificates(id),

    last_tested_at TEXT,
    last_result    TEXT    NOT NULL DEFAULT '',
    tools_ok       INTEGER CHECK (tools_ok IN (0, 1)),   -- NULL until tested

    added_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    added_by       INTEGER,
    updated_at     TEXT
);
