# NASQuay

Self-hosted operation of QNAP NAS units: a web interface, scheduled routines and an MCP
endpoint for AI tools — all behind one set of users, roles and per-action permissions, with
every action recorded.

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
- **Safe by default.** Destructive actions need confirmation from a person, and unattended
  callers cannot perform them unless explicitly allowed.
- **Guides.** `docs/ADMIN_GUIDE.md` and `docs/USER_GUIDE.md`, and a help button on every page
  explaining what it shows and where its figures come from.

## Requirements

- A host running Ubuntu 22.04 or 24.04 LTS with Python 3.11+, systemd and Node 20+ for the
  build.
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
and installs the `nasquay-web` service.

Put a TLS reverse proxy in front of it before using it from other machines; the default listen
address is `127.0.0.1`.

To remove it, keeping or discarding its data:

```bash
bash uninstall.sh              # service, environment and all data
bash uninstall.sh --keep-data  # keeps config.yaml, the database, secrets and logs
```

## Documentation

- `docs/DESIGN.md` — what NASQuay is, how the permission gate works, and the decisions behind it.

## Licence

PolyForm Noncommercial License 1.0.0 — see `LICENSE`. Any noncommercial purpose is permitted,
including personal use and use by charities, schools, public research and government bodies.

Required Notice: Copyright Robert Barnett (https://pktSolution.com)
