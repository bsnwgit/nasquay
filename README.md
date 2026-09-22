# NASQuay

**Self-hosted monitoring, automation and a web dashboard for QNAP NAS storage.** NASQuay
watches your pools, volumes, shares and client mounts from several independent angles,
raises a flag the moment something disagrees with what it should be, and keeps a history
so a change can be recognised as a change rather than guessed at afterwards. A web
interface, scheduled routines, generated reports and an MCP endpoint for AI tools all sit
behind one set of users, roles and per-action permissions, with every action recorded.

It runs entirely on your own hardware, talks to your NAS units directly, and sends nothing
to any third party unless you configure an AI provider or notification channel yourself.

> **Independent project.** NASQuay is not affiliated with, endorsed by or sponsored by
> QNAP Systems, Inc. "QNAP" and "QTS" are trademarks of QNAP Systems, Inc. and are used
> here only to describe compatibility.

NASQuay drives QNAP's own MCP Assistant, which runs on each NAS, and uses SSH only for the
few readings it has no tool for. Nothing extra is installed on a NAS.

## What it does

- **Web interface** for storage, shares and files, NAS accounts, logs, security and system.
- **Users and roles.** Every action the app can perform is switched on or off per role. An
  admin can only be disabled if another admin remains.
- **One gate.** The pages, the embedded assistant, routines and the MCP endpoint all call the
  same actions, so one permission check and one audit record cover every route in.
- **Monitoring** of pools, volumes, shares and the machines that mount them, from several
  independent angles, to catch divergence between what a NAS reports and what is actually
  there. Collection runs on its own schedule and builds a history; a NAS's own usage history
  can be imported so there is a baseline from the first day.
- **Notifications** by email, ntfy push or Slack when a rule fires, and again when it clears.
- **Routines** — scheduled work that runs as a chosen user with nobody watching: a fixed list
  of steps, or a prompt handed to a model with the operations you allow it. Every call passes
  the same gate and is recorded.
- **Reports** — capacity, change, health and activity over a period, optionally compared with
  the period before, readable on the page and downloadable as PDF or CSV, with an optional
  AI-written summary that is always marked as one. Built from what was recorded, so producing
  one never contacts a NAS.
- **AI provider agnostic** — any OpenAI-compatible server (Ollama, LM Studio, vLLM, OpenAI) or
  the Anthropic API, configured in the app and tested from it.
- **An MCP endpoint** for AI tools outside NASQuay, reached with a personal API token that is
  read-only unless you say otherwise, hashed at rest, expiring and revocable.
- **Safe by default.** Destructive actions need confirmation from a person, and unattended
  callers cannot perform them unless explicitly allowed.
- **Guides.** `docs/ADMIN_GUIDE.md` and `docs/USER_GUIDE.md`, and a help button on every page
  explaining what it shows and where its figures come from.

## Requirements

- A host running Ubuntu 22.04 or 24.04 LTS with Python 3.11+, systemd and Node 20+ for the
  build. Python dependencies are in `requirements.txt`; nothing needs system libraries beyond
  a working Python.
- One or more QNAP NAS units running QTS 5.2+ or QuTS hero h5.2+, with QNAP's **MCP Assistant**
  installed from App Center.
- A token from MCP Assistant for each NAS, and optionally an SSH account on it.

## Install

```bash
git clone git@github.com:bsnwgit/nasquay.git
cd nasquay
bash install.sh
```

The installer asks for the install directory, the listen address and port, and the first admin
account. It creates the virtual environment, writes `config.yaml` with freshly generated keys,
applies the database migrations, and installs two services: **`nasquay-web`** for the API and
the interface, and **`nasquay-worker`** for the monitoring schedule, the routines and the
reports. Without the worker, nothing runs on its own.

Put a TLS reverse proxy in front of it before using it from other machines; the default listen
address is `127.0.0.1`.

To remove it, keeping or discarding its data:

```bash
bash uninstall.sh              # service, environment and all data
bash uninstall.sh --keep-data  # keeps config.yaml, the database, secrets and logs
```

## Documentation

- `docs/ADMIN_GUIDE.md` — installing, connecting a NAS, roles, monitoring, routines, reports,
  the assistant, the MCP endpoint and what to do when something is wrong.
- `docs/USER_GUIDE.md` — using it: what each page shows and where its figures come from.
- `docs/DESIGN.md` — what NASQuay is, how the permission gate works, and the decisions behind it.

Every page also carries a help button explaining that page and the provenance of its figures.

## Licence

PolyForm Noncommercial License 1.0.0 — see `LICENSE`. Any noncommercial purpose is permitted,
including personal use and use by charities, schools, public research and government bodies.

Required Notice: Copyright Robert Barnett (https://pktSolution.com)

## Disclaimer

This is an independent, community project with no relationship to QNAP Systems, Inc. It is
not affiliated with, endorsed by, sponsored by or in any way officially connected with QNAP,
or with any of its subsidiaries or affiliates. "QNAP", "QTS", "QuTS hero" and any other QNAP
product or service names are trademarks or registered trademarks of QNAP Systems, Inc. Any
use of these names in this project is for identification and compatibility purposes only.
