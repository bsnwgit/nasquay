# NASQuay — design

**Status:** draft for review. Nothing here is built. Items marked **Decision** are listed at the
end with their answers; open ones need an answer before the part they affect is written.

## Purpose

NASQuay is a self-hosted web application for operating QNAP NAS units. It gives people a web
interface, an embedded AI assistant, scheduled routines and an MCP endpoint for outside AI
tools — and puts every one of those behind the same users, roles and per-action permissions,
with every action recorded.

It is built to be installed by anyone on their own host. Nothing about a particular network is
built in: every NAS, credential, AI provider, schedule and threshold is a setting.

## Principles

- **One gate.** The web interface, the embedded assistant, routines and the MCP endpoint all
  perform work by calling *actions*. Every action call passes one permission check and writes
  one audit record. There is no second path to a NAS.
- **Permission before contact.** A request the caller's role does not allow is refused before
  anything is sent to a NAS.
- **The NAS does the work.** NASQuay drives QNAP's own MCP Assistant on each NAS and uses SSH
  only for what that does not provide. Nothing extra is installed on a NAS.
- **Provider agnostic.** Any OpenAI-compatible server (including a local Ollama) or the
  Anthropic API can back the assistant and routines. Nothing assumes a particular model size.
- **Safe by default.** Destructive actions need confirmation from a person; unattended callers
  cannot perform them unless explicitly allowed.

## Architecture

```
 browser ── web UI (React) ───────────────┐
 browser ── embedded resonance ── calls ──┤
 outside AI tool ── MCP endpoint ─────────┤
 worker ── routines, monitoring, jobs ────┤
                                          ▼
                        ┌──────── NASQuay API (FastAPI) ────────┐
                        │  auth ─► permission gate ─► audit      │
                        │               │                         │
                        │         action registry                 │
                        │        ┌──────┴───────┐                 │
                        │   QNAP MCP client   SSH runner          │
                        └────────┬───────────────┬────────────────┘
                                 ▼               ▼
                     NAS: MCP Assistant (:8443)  NAS: shell (df, du, find)

                        SQLite: users, roles, permissions, NAS, actions,
                        jobs, audit, routines, readings, settings
```

Two processes, both systemd services on the host:

- **web** — the API, the React app, the MCP endpoint and the resonance integration.
- **worker** — runs jobs, routines and monitoring collection on their schedules. Restarts on
  failure and starts at boot, so nothing silently stops after a power cut.

**Stack (decided):** Python 3.11+, FastAPI and Pydantic v2 for the backend; React 18,
TypeScript, Vite and Tailwind for the frontend — the same stack as the rest of the suite, so the
suite's resonance mount can be reused.

## Actions

An action is the unit of everything NASQuay can do.

| Field | Meaning |
|---|---|
| `id` | stable name, e.g. `storage.list_volumes`, `files.move` |
| `source` | `qnap_mcp` (a QNAP tool), `ssh` (an allow-listed command), or `app` (NASQuay itself) |
| `category` | storage, files, shares, nas-users, logs, security, system, apps, monitoring, admin |
| `classification` | `read`, `write` or `destructive` — NASQuay's own, reviewed |
| `params` | Pydantic schema; paths are validated and confined to a share |
| `long_running` | runs as a job and returns a job id instead of blocking |

Rules:

- **QNAP's tool annotations are not used.** On the version examined, every tool — reads
  included — reports `readOnlyHint=false, destructiveHint=true`, so they carry no information.
  NASQuay ships a reviewed catalogue of known QNAP tools with its own classification.
- **Unknown tools** discovered on a NAS (new firmware, new app version) are not offered until
  reviewed. **Decision 9.**
- **SSH actions** are fixed, allow-listed commands with validated arguments (`df`, `du`, file
  counts). There is no free-form shell action unless **Decision 10** says otherwise.
- **App actions** cover NASQuay's own functions: users, roles, settings, routines, tokens.
  They go through the same gate, so "manage users" is a permission like any other.

## Users, roles and permissions

- Users are created, modified, disabled and removed in the app.
- Roles are created, modified and removed in the app. A built-in **admin** role holds every
  permission and cannot be edited.
- A role holds an on/off switch **for every action**. New actions default to off for every role
  except admin.
- **Last admin guard:** an admin cannot be disabled, removed or moved to another role unless
  another enabled admin remains. Enforced in the backend, not just the UI.
- **First admin** is created by a prompt during install. There is no default password.
- Authentication follows the suite's local pattern: short-lived access tokens and a refresh
  token in an HTTP-only cookie; passwords hashed; login rate-limited.
- **Permission scope — Decision 8:** per action only, or per action *per NAS* (a role may run
  `files.move` on one NAS but not another).

### Callers other than a person at the page

| Caller | Acts as | Notes |
|---|---|---|
| Embedded resonance | the signed-in user | calls come through that user's browser session |
| Routine | its **run-as** user | set by an admin per routine |
| MCP endpoint | the owner of the **API token** | tokens are per user, revocable, hashed at rest |

Unattended callers (routines, API tokens) cannot run `destructive` actions unless the routine or
token is explicitly allowed to. **Decision 11.**

## Audit log

Every action attempt is recorded, allowed or denied:

- when; who (user, token, routine); through what (web, resonance, routine, MCP)
- action, NAS, parameters with secrets redacted
- decision (allowed or denied, and why), outcome, duration, job id

The audit log is read through an action (`admin.read_audit`), so who may see it is itself a
permission.

## NAS connections

Managed on the settings page: add, modify, remove, enable, disable, and **Test connection**
(MCP handshake and SSH login, result shown).

Per NAS:

- name, address, MCP endpoint URL
- MCP token — **Decision 7** (how secrets are entered and stored)
- TLS handling for the MCP endpoint — **Decision 4**
- SSH account, host key, and the host's SSH public key shown for authorising it on the NAS
- discovered pools, volumes and shares, picked from lists rather than typed

### QNAP MCP client

Observed on MCP Assistant 1.0.0.2356, QTS 5.2.x:

- Streamable HTTP at `/mcp` on port 8443 (HTTPS) or 8442 (HTTP); `/sse` also served.
- `Authorization: Bearer <token>`; `initialize` returns an `Mcp-Session-Id` that every later
  request must carry.
- Python `http.client` over HTTP/1.1 works, on one connection or several. curl over HTTP/2 got
  `404 Invalid session ID` for every request after `initialize`. **Use HTTP/1.1.**
- Unauthenticated requests get `401`; a bad token gets `401 credential not valid`.
- A token created with default settings exposed 42 tools: storage, pools, volumes, disks, shared
  folders and permissions, files (list, search, share link), NAS users and groups, logs, system
  info and load, app list, firmware check, security and malware scans and reports, power
  schedule. Copy, move and rename appear in QNAP's product description but not in that list —
  the full list with write access enabled is still to be checked.

**Token privilege.** NASQuay enforces permissions itself, so each NAS token must allow
everything NASQuay is meant to offer. A read-only token makes every write fail, even for an
admin. Tokens are powerful and never leave the host.

### Data quirks the app must handle

- **Per-share `file_count` / `dir_count` are cached.** They stayed constant while a live count
  rose. Shown as "last computed by the NAS", never used by a rule.
- **Volume free space is live.** It matched `df` on one volume to within 128 KB; on a busy
  volume the two differed by ~7.8 GB, so comparisons need a calibrated margin.
- **Usage history units are wrong.** `get_qts_volume_usage_history` returns rounded binary
  figures scaled by decimal powers and labelled bytes: `7,680,000,000,000` is 7.68 TiB,
  `808,910,000,000` is 808.91 GiB. Convert `x × 10^(3k)` to `x × 1024^k`, keep the raw value,
  mark it rounded. The derived `used_human` is wrong for the same reason.
- History resolutions: past hour (~10 min), 12 h (~20 min), day (hourly), week (4 h), 30 days
  (daily), year (weekly). Weekly points are not samples of the daily series.
- **Access log entries are codes, and QNAP publishes no key.** `list_access_logs` returns
  numeric `service` and `action` where QuLog Center shows words, and no message field, so a
  warning row explains nothing on its own. The mapping below was derived by exporting QuLog's
  own CSV and joining it to the same rows read over MCP on date, time, user, address and
  resource — 2,000 of 2,000 rows matched:

  | `service` | | `action` | |
  |---|---|---|---|
  | 1 | SMB | 2 | read |
  | 8 | NFS | 4 | write |
  | 64 | SSH/SFTP | 16 | create directory |
  | 1024 | HTTPS | 256 | login failed |
  | | | 512 | login |
  | | | 1024 | logout |
  | | | 16384 | add |

  A code outside these tables is shown as a number rather than given a plausible label.
  Note that a failed *public-key* SSH attempt is recorded nowhere — only an attempt that
  reaches password or keyboard-interactive authentication becomes a `login failed` row, so
  the absence of an entry is not evidence that nothing was tried.
- **QNAP `df` wraps long device names**; numbers can be on the following line.
- **SSH key login** needs QTS home folders enabled and a home that is not group- or
  world-writable.

## Web interface

- **Dashboard:** every NAS at a glance — pools, volumes, health, open flags, recent routine runs.
- **Areas**, each built from the actions the user's role allows:
  storage (pools, volumes, disks), shares and files, NAS users and groups, logs, security
  (scans, reports, policy), system (info, load, processes, firmware, apps, power schedule),
  monitoring, routines, jobs, audit.
- An action the user may not run is not offered.
- **Destructive actions** show what will happen and need explicit confirmation.
- **Jobs** view for long-running actions: progress, result, cancel where the NAS supports it.
- **Dashboard access** is a setting: open to anyone who can reach the page, or login required
  (default).

### Settings

All admin-only, and each section is itself a permission:

- **NAS units** — connections as above.
- **Users and roles** — users, roles, the permission grid (every action × every role).
- **API tokens** — per user; create, revoke, see last use.
- **AI providers** — see below.
- **Routines** — see below.
- **Monitoring** — watched targets, intervals, thresholds.
- **Resonance** — embed on/off, resonance address, key, appearance.
- **General** — dashboard access, session lifetime, audit retention.

## Monitoring

Built in, using the same actions and gate (run as a system user with read-only permissions).

- **Fast tier** (proposed every 10 min): pool status, volume capacity and free space via MCP;
  `df -k` per volume via SSH; client mount presence and `df` if client views are configured.
- **Slow tier** (proposed hourly for file counts, every 6 h for `du`): live file count per share,
  `du -sk` per share.
- **Backfill** from MCP usage history on first connection, so there is a baseline from day one.
- Intervals are settings. **Decision 1:** defaults.
- **Client view — Decision 5:** the host mounts shares itself, or runs `df` over SSH on an
  existing client machine.

Readings are narrow rows (target, metric, value in integer bytes or counts, source, rounded,
cached, backfilled). `df` and `du` run with `-k`, so no human-readable units are parsed.

Rules, thresholds set on the settings page and tuned after real readings:

| Rule | Fires when |
|---|---|
| `volume_drop` | used space on a volume falls more than X% within a window (proposed 5% in 1 h) |
| `file_count_drop` | a share's live file count falls by more than N files or X% between readings |
| `df_vs_du` | the sum of `du` for a volume's shares differs from `df` used beyond a calibrated margin |
| `client_vs_nas` | a client's view of a mount differs from the NAS's view beyond the margin |
| `mcp_vs_df` | MCP free space differs from `df` beyond the calibrated margin |
| `mount_missing` | a configured client mount is absent |
| `pool_status_change` | a pool's status changes. **Decision 2:** also flag while it stays degraded? |
| `worker_stale` | the worker has not completed a fast-tier run for 2× its interval |

Flags appear on the dashboard. **Decision 3:** notifications beyond the page.

## Embedded resonance

NASQuay embeds resonance the way the other suite apps do, reusing the suite's resonance
integration package and React mount.

- NASQuay publishes its actions to resonance as an OpenAPI description plus a grant file.
  Resonance's admin chooses which operations the assistant may use.
- The assistant's calls go through the signed-in user's browser session, so **the user's role
  applies** exactly as if they had clicked.
- Resonance limits to design around: at most 4 tool rounds per question, 20 s per call,
  results truncated at 4,000 characters, and writes need the person's confirmation.
  Long-running actions therefore return a job id and a short summary; the assistant can check
  the job afterwards.
- Resonance does not schedule anything and does not speak MCP. Routines and the MCP endpoint are
  NASQuay's own.

## AI providers and routines

### Providers

Configured on the settings page; any number.

- **Kinds:** OpenAI-compatible (base URL — covers Ollama, LM Studio, vLLM, OpenAI) and Anthropic.
- **Fields:** name, kind, base URL, model, API key (**Decision 7**), timeout, and whether the
  model supports tool calling. Small local models often handle tools poorly, so a routine can
  require a tool-capable provider.
- A **Test** button sends a trivial request and a trivial tool call.

### Routines

A routine is a scheduled piece of work, created and edited on the settings page.

- **Schedule:** interval or cron expression; enabled or disabled.
- **Run-as user:** its permissions are that user's; a routine can never do more.
- **Kind:**
  - **fixed** — an ordered list of actions with parameters, no AI involved;
  - **AI** — a prompt, a provider, and the subset of actions the model may call. The worker runs
    the model with those actions as tools, looping until it answers or hits the routine's step
    limit.
- **Destructive actions** blocked unless the routine explicitly allows them (**Decision 11**).
- Every run is recorded: start, end, status, each action called (also in the audit log), final
  output. Failures and flags raised can alert (**Decision 3**).

## MCP endpoint

For outside AI tools that speak MCP.

- Streamable HTTP at `/mcp` on the NASQuay host, behind its TLS proxy.
- Authenticated by a **per-user API token**; the tool list is filtered to the actions that
  user's role allows, and every call goes through the gate and the audit log.
- Long-running actions return a job id plus a `jobs.status` tool.
- Destructive actions follow **Decision 11** — an AI tool has no confirmation dialog.

## Data model

SQLite in WAL mode; schema changes through numbered migrations.

```
users            id, username, display_name, password_hash, role_id, enabled, created_at, last_login_at
roles            id, name, description, builtin
role_permissions role_id, action_id, [nas_id], allowed
api_tokens       id, user_id, name, token_hash, allow_destructive, created_at, last_used_at, expires_at, revoked_at
nas              id, name, address, mcp_url, tls_mode, tls_fingerprint, ssh_user, ssh_host_key, enabled
actions          id, source, name, category, classification, params_schema, long_running, reviewed
jobs             id, action_id, nas_id, requested_by, via, params, status, progress, result, error, started_at, finished_at
audit            id, at, actor_kind, actor_id, via, action_id, nas_id, params_redacted, decision, reason, outcome, duration_ms, job_id
ai_providers     id, name, kind, base_url, model, supports_tools, timeout_s
routines         id, name, enabled, schedule, kind, run_as_user_id, steps, prompt, provider_id, allowed_actions, allow_destructive, max_steps
routine_runs     id, routine_id, started_at, finished_at, status, output
targets          id, nas_id, kind, ref, enabled
readings         id, taken_at, target_id, metric, value, source, rounded, cached, backfilled, raw
flags            id, raised_at, rule, target_id, severity, detail, cleared_at
settings         key, value
```

Where secrets live depends on **Decision 7**.

## Configuration

`config.yaml` holds startup settings only and is never committed; `config.example.yaml` is the
tracked template. Environment variables (`NASQUAY_*`) override the file.

```yaml
database: /opt/nasquay/data/nasquay.db
listen: 127.0.0.1:<port>
public_url: https://nasquay.example.com
secrets_dir: /opt/nasquay/secrets
ssh_key: /opt/nasquay/secrets/id_ed25519

# Everything else — NAS units, users, roles, permissions, AI providers, routines, monitoring,
# resonance, dashboard access — is a runtime setting managed in the app.
```

## Security

- Every endpoint has an explicit authentication dependency and permission check; there are no
  internal routes.
- All SQL parameterised. All input validated and bounded with Pydantic.
- File-action paths resolved and confined to their share.
- Anything rendered from NAS data (file names, log lines, user names) is escaped.
- Cookie-authenticated requests are protected against cross-site request forgery.
- Secrets are never returned by the API or shown in the UI once saved.
- SSH uses `BatchMode`, a pinned host key and only allow-listed commands.
- TLS verification to a NAS is never disabled silently (**Decision 4**).

## Deployment and packaging

- `install.sh` for Ubuntu 22.04 / 24.04: creates the service user, venv and directories under
  `/opt/nasquay`, builds the frontend, writes `config.yaml`, prompts for the first admin,
  installs `nasquay-web.service`, and `nasquay-worker.service` once the worker itself is
  built — today the installer writes the web unit only.
- Reverse-proxy example with TLS for the host's own certificate.
- Data, logs, secrets and `config.yaml` live beside the code and are preserved by upgrades.
- `VERSION` file in the suite's `Major.Minor.Patch.CodeName[.Hotfix]` format.
- Install path, port and hostname on a given host: **Decision 6**.

## Repository layout

```
nasquay/
├── app/
│   ├── main.py              FastAPI app, routers, lifespan
│   ├── config.py            startup config: env > config.yaml > defaults
│   ├── database.py          SQLite, migrations
│   ├── auth/                local accounts, tokens, sessions
│   ├── api/                 one router per resource
│   ├── actions/             registry, gate, audit, QNAP catalogue
│   ├── connectors/          qnap_mcp.py, ssh.py
│   ├── worker/              scheduler, jobs, routines, monitoring
│   ├── ai/                  providers, tool loop
│   ├── mcp/                 MCP endpoint
│   └── integrations/
│       └── resonance/       the suite's resonance package
├── frontend/                React + TypeScript + Vite + Tailwind
├── migrations/
├── deploy/                  systemd units, reverse-proxy example
├── scripts/                 version bump and maintenance
├── tests/                   actions, gate, parsers, rules — synthetic fixtures only
├── docs/                    DESIGN.md, ADMIN_GUIDE.md, USER_GUIDE.md
├── install.sh
├── config.example.yaml
├── requirements.txt
└── VERSION
```

## Build order

Each step is deployed to a test host and checked before it is committed.

1. **Core app** — database, settings, install with first-admin prompt; users, roles,
   permission grid, last-admin guard, audit log.
2. **NAS connections** — NAS settings and test connection; QNAP MCP client and SSH runner;
   action registry and the reviewed QNAP catalogue.
3. **Web interface** — dashboard and areas; confirmations; jobs.
4. **Monitoring** — worker, collection tiers, backfill, rules, flags.
5. **Embedded resonance.**
6. **AI providers and routines.**
7. **MCP endpoint.**
8. **Packaging** — installer hardening, admin and user guides.

A project website is a separate project.

## Out of scope

- Replacing QTS. NASQuay drives what the NAS exposes; it does not reimplement the NAS.
- Backups and snapshots. NASQuay can show that data went missing; it cannot restore it.
- Storing file contents.
- NAS brands other than QNAP — the connector layer leaves room, but nothing else is planned.

## Decisions

Decided 2026-09-15:

1. **Monitoring intervals:** fast tier every 10 min, file counts hourly, `du` every 6 h — all
   adjustable in settings. Time `du` on the largest volume before relying on the 6-hour default.
2. **Degraded pools:** flag when a pool's status changes, and show a persistent "degraded"
   badge for as long as it stays degraded.
3. **Notifications:** email **and push**, configured in settings, for flags and routine
   failures.
4. **NAS certificates:** pin each NAS certificate's fingerprint — shown at Test connection for an
   admin to accept, and connections refused if it changes. Admins can also **add a certificate**
   (the NAS's own, or a CA) to trust.
5. **Client view:** `df` over SSH on client machines, optional per client.
6. **Install:** default `/opt/nasquay`. The test host's path, port and hostname are decided and
   kept out of this document.
7. **Secrets:** entered in write-only fields and stored encrypted in the database; the
   encryption key is kept on the host, outside the database.
8. **Permissions:** per action, with optional per-NAS overrides.
9. **Unreviewed QNAP tools:** hidden until an admin reviews and classifies them.
10. **Shell action:** never.
11. **Destructive actions from routines and API tokens:** blocked unless that routine or token is
    explicitly allowed.
12. **Push:** ntfy first (self-hostable, phone apps); Pushover and browser notifications may be
    added later.

No design decisions are open.
