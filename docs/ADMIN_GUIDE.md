# NASQuay — administrator's guide

Everything in this guide is done from the web interface unless it says otherwise. Every
action described here passes the same permission check and is written to the audit log,
including the ones that fail.

---

## Installing

A host running Ubuntu 22.04 or 24.04 LTS, Python 3.11 or newer, systemd, and Node 20+ to
build the interface.

```
bash install.sh
```

Run it as your ordinary user, not with `sudo` — it calls `sudo` itself for the few steps
that need it, and refuses to run if you start it as root.

It asks three things:

- **Where to install.** Default `/opt/nasquay`. It refuses to install into your home
  directory.
- **What address to listen on**, chosen from a numbered list of what the host actually has.
  `127.0.0.1` is right when a reverse proxy sits in front and terminates TLS; `0.0.0.0`
  exposes it on every interface. Re-running the installer asks whether to change it.
- **The first administrator** — a username and password. This account cannot be locked out:
  the last remaining administrator cannot be disabled, demoted or deleted, by the interface
  or by the database.

It creates a Python virtual environment, builds the interface, writes `config.yaml`,
generates an SSH key and an encryption key under `secrets/`, applies the database
migrations and installs the `nasquay-web` systemd unit.

**Put TLS in front of it.** NASQuay speaks plain HTTP and expects a reverse proxy to
terminate TLS. Sign-in sends a password; do not expose it directly.

### Upgrading

Deploy the new files and restart the service. Migrations apply themselves at startup, in
order, each exactly once. `config.yaml`, the database, `secrets/` and `logs/` are never
touched by an upgrade.

Anything that changes Python code, adds a migration or adds an action needs a restart to
take effect. Changes to the interface alone do not.

---

## Connecting a NAS

**Settings → NAS.**

On the NAS itself, first: install **MCP Assistant** from App Center (QTS 5.2+ or QuTS hero
h5.2+), and create a **Token** credential in it. NASQuay speaks streamable HTTP to it over
HTTPS, normally port 8443.

A NAS is verified one of three ways, chosen under **Certificate** on its settings:

- **Pinned** — the default. Adding a NAS is two steps on purpose: **read the certificate**
  it presents and look at the fingerprint, then **save it** with the token. From then on
  that exact certificate is required. A NAS presenting a different one is refused rather
  than trusted, and says so — if the certificate was genuinely replaced, accept the new one
  here. This is the right choice for the self-signed certificate a QNAP ships with.
- **An uploaded certificate** — upload the authority that issued your certificates under
  **Settings → Certificates**, then choose it here. The chain *and* the name are checked,
  and one upload covers every NAS that authority issued for. Because the name is checked,
  the address recorded for the NAS must be one the certificate covers: a certificate issued
  for a hostname will not verify a NAS reached by its IP address.
- **The host's certificate store** — for a NAS holding a certificate from a public
  authority.

### Certificates

**Settings → Certificates.** Upload a `.crt`, `.pem` or `.cer` file, or paste the PEM text;
an intermediate and a root can go in together. NASQuay shows what the certificate says
about itself — subject, issuer, validity and SHA-256 fingerprint — before anything is
verified against it, and marks one that has expired.

Nothing here is a credential: a certificate is the public half by definition, so unlike a
token it goes in and comes back out. A file containing a **private key is refused** —
NASQuay never needs the private half of anything a NAS presents. A certificate a NAS is
still verified against cannot be deleted.

Tokens go in but never come out. The API reports only whether one is set, and leaving the
field empty when editing keeps the stored token, so saving the form does not wipe it.

**SSH is optional but worth having.** A few readings have no MCP tool: the real size of a
share, a live file count, and `df`. Give NASQuay an account on the NAS and authorise its
public key (see *SSH keys* below). Only fixed commands are ever run — `df -k`, `du -sk` and
`find` — and there is no path by which a free-form command can be sent to a NAS.

**The administration interface** is a separate field. Record the address of the NAS's own
web interface — `https://10.0.0.10:8080`, or whatever name and port it answers to — and the
home page shows it as a link that opens in a new tab. It is not derived from the address
NASQuay talks MCP to, because that is the MCP port and a NAS may also sit behind a proxy or
answer to another name. Nothing about the target is fetched, checked or proxied: following
the link simply leaves NASQuay. Emptying the field removes the link.

QNAP's own requirements catch people out here: key login needs home folders enabled in
Control Panel → Privilege → Users, `~/.ssh` at mode 700, `authorized_keys` at 600, and a
home directory that is not group- or world-writable.

### Tools

**Settings → NAS**, expanding a unit. Discovery asks the NAS which tools it offers — 42 on
QTS 5.2.x — and each becomes an action that roles can be granted or refused individually.

QNAP's own annotations are useless: every tool reports itself as destructive, reads
included. NASQuay classifies them itself. **A tool NASQuay does not recognise arrives
unreviewed, and an unreviewed tool can be run by nobody, administrators included**, until
somebody classifies it. Rediscovery never overwrites a review or the permissions hanging
off it.

---

## Users, roles and permissions

**Settings → Users** and **Settings → Roles**.

A role is a set of switches, one per action — NASQuay's own actions and every tool every NAS
offers. The grid is large on purpose: there is no category-level shortcut that quietly grants
something you did not look at.

Permissions can also be overridden per NAS, so a role may read one box and not another.

The check happens **before anything is sent to a NAS**, and covers every way in: these pages,
scheduled routines and the API alike. There are no internal routes that skip it.

**The last administrator is protected** by the API and by database triggers, so neither a
mistake in the interface nor a direct write can leave the installation with no way in.

---

## SSH keys

**Settings → SSH keys.**

NASQuay generates keys, names them, and shows the **public** half. The private half never
leaves the host: no page shows it, no endpoint returns it, and nothing in the application
reads it — its path is handed to `ssh` and that is all.

- **Add key** generates an ed25519 key. No passphrase, deliberately: NASQuay connects
  unattended and nothing can type one, so a passphrase would mean a key that does not work.
  The protection is the file mode and the fact that it stays on the host.
- **Copy install command** gives you `ssh-copy-id …` to run **on the NASQuay host**, since
  that is where the key lives. It asks for the remote password once — the thing it replaces.
- **Rename** moves the files and repoints every client that named the key, and puts the
  files back if that fails, so the two never end up out of step.
- A key in use cannot be deleted, and the key `install.sh` made cannot be deleted or renamed
  here, because its path comes from the configuration.

The install's own key is listed too. It is the default for everything and the one your NAS
units already trust.

---

## Monitoring

**Settings → Monitoring**, in three tabs.

### Schedule

Off by default. An application that starts walking a 28 TB share because it was installed is
not a good guest — you turn it on.

Three tiers run independently, at the three costs the measurements actually have:

| Tier | Reads | Sensible interval |
|---|---|---|
| Fast | Pool status, volume capacity and free space, `df` | minutes |
| Deep | `du` and a live `find` per share | hours |
| Client | Whether each client mount is present, and its `df` | minutes |

A run already in progress is never started twice, so a deep read that outlasts its interval
delays the next one rather than piling up.

The same tab holds the rule thresholds. They are settings rather than constants because what
counts as normal movement is a property of your hardware, and they are meant to be tuned once
there are real readings to tune against.

### Watched

**Discover** asks a NAS what exists and makes a target of each pool, volume and share. Switch
each on or off.

Discovery **never removes** a target. A share that stops being reported keeps its history and
simply stops gaining readings, because a share disappearing is exactly what this is here to
catch.

**Import history** pulls the NAS's own usage figures — about a year — so there is a baseline
from the first day rather than after weeks of collecting. Those figures are rounded to three
or four significant digits and are mislabelled by QNAP, so NASQuay converts them back and
marks every one as rounded and backfilled. No rule will compare against them.

### Clients

A client is a machine that **mounts** a share. A share can be perfectly healthy on the NAS
while the machine that needs it has silently lost the mount, and nothing on the NAS side
shows that.

Add the machine, choose which key to reach it with, then **Look** to read its own mount table
and add a mount from what is actually there. NASQuay asks it two fixed questions: is this path
mounted, and what does `df` say. `mount` is consulted rather than `df` alone, because `df` of
an unmounted path quietly answers about the disk underneath and looks healthy.

---

## Rules and flags

Eight rules run after every collection. A flag is raised **once** and cleared when the
condition stops holding, so the record of what was seen survives the condition ending.

| Rule | Fires when |
|---|---|
| `volume_drop` | used space on a volume falls by more than the threshold within the window |
| `file_count_drop` | a share loses more than N files, or more than X% of them |
| `df_vs_du` | the shares on a volume do not add up to what `df` says it holds |
| `mcp_vs_df` | the NAS's own free space and `df` disagree |
| `pool_status_change` | a pool's status changes at all |
| `mount_missing` | a watched mount is absent on its client |
| `client_vs_nas` | a client's view of a filesystem differs from the NAS's |
| `collection_stale` | no collection has completed in twice the interval |

Three things worth knowing about how they behave:

- **No rule trusts a degraded figure.** A reading marked rounded, cached or backfilled is
  excluded from any comparison. Imported history is there to be looked at, not to fire alarms.
- **A rule that cannot be evaluated says nothing.** `df_vs_du` skips a volume unless every
  share on it is watched and has an exact `du`, because a partial sum is always short and
  would flag for ever while meaning nothing.
- **`collection_stale` is only asked when the schedule is on.** With it off, nothing
  collecting is the correct state rather than a fault.

Clearing a flag by hand does not stop the rule: if the condition still holds, the next
collection raises it again.

---

## Notifications

**Settings → Notifications.**

Three channels, each optional and independent — **email** for a record that stays, **ntfy**
for a push that reaches a phone, and **Slack** for where people are already looking. Any can
be on without the others, and one failing never stops another.

Choose what is worth sending. Errors are on by default and warnings are off: a divergence of
a few percent belongs on a page, not at three in the morning. Clearings are sent too, because
knowing a thing fixed itself is as useful as knowing it broke.

Because a flag is raised once and cleared once, this is **one message per condition**, not one
every few minutes while it holds.

The mail password, the ntfy token and the Slack webhook are credentials: encrypted at rest,
never returned by the API, and a blank box on save keeps what is stored rather than erasing
it. **Send a test** delivers on every enabled channel now and reports exactly what happened.

---

## When something is wrong

- **The Trouble panel** at the top of the Dashboard, the NAS page and the Clients page shows
  any recent collection that failed or only partly worked, with the reason. It shows only
  failures since the last run that worked, so a fixed fault stops shouting. Scheduled runs
  fail while nobody is watching; this is where they surface.
- **Settings → General** shows whether a saved change is waiting for a restart.
- **The audit log** records every action, including refusals and why they were refused.
- The service log is `logs/nasquay-web.log` in the install directory.

A reading marked **cached** came from a figure the NAS computed earlier and hands back
unchanged. One marked **rounded** lost accuracy before NASQuay saw it. Neither is trusted by
a rule, and both say so on the page.

---

## Backing up

What matters lives in the install directory and is never touched by an upgrade:

- `config.yaml` — startup configuration
- `data/nasquay.db` — users, roles, NAS units, targets, readings, flags, the audit log
- `secrets/` — the encryption key and the SSH keys

**Back up `secrets/` with the database.** Every stored token, password and webhook is
encrypted with the key in there. Without it the database still opens, but nothing NASQuay
needs to authenticate with can be read back.

---

## Uninstalling

```
bash uninstall.sh              # removes the service, venv and all data
bash uninstall.sh --keep-data  # keeps config.yaml, data/, secrets/ and logs/
```

Installed in place, it leaves the application files so `install.sh` can run again.
