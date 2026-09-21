# NASQuay — user's guide

NASQuay looks at QNAP NAS units and keeps a history of what it saw, so that a change can be
recognised as a change rather than guessed at afterwards.

Every page carries a **?** in a blue circle beside its title. It explains what that page
shows and where its figures come from. This guide is the longer version of the same thing.

---

## Signing in

Your NASQuay account is not an account on any NAS. Your role decides what you may do; an
administrator sets it.

Anything you are not permitted to do is not offered, and if you reach it another way it is
refused and the refusal is recorded. Nothing you do is invisible — every action lands in the
audit log under your name, successful or not.

Your own account is behind your name at the top right. Changing your password there signs out
your other sessions.

---

## Finding your way round

Five groups along the top, each opening on an overview with its own list on the left.

| Group | Holds |
|---|---|
| **Home** | the NAS units NASQuay knows, when each was last checked, and a link to each one's own interface where an administrator has recorded it |
| **Storage** | Overview, Pools, Shares, Files — an administrator can leave shares and folders out of these listings; the page says how many |
| **Activity** | Dashboard, NAS, Clients, Logs, Audit |
| **System** | Overview, Accounts, System, Security |
| **Settings** | configuration, for administrators |

---

## Is anything wrong?

**Activity → Dashboard.** One screen, and the only one built to answer that question.

A headline that counts what is flagged and whether collection is working, then the open
flags, then volume usage — amber past 75%, red past 90% — and whether each client mount is
present.

It contacts no NAS. Every figure was already recorded, so opening it costs nothing and wakes
nothing up. That is also why it shows the **age of the newest reading**: a calm dashboard of
stale figures is worse than no dashboard.

If a collection has failed, a panel at the top says so and why. It only shows failures since
the last run that worked, so something already fixed stops shouting.

---

## Looking at storage

**Storage → Overview** puts every NAS's pools and volumes side by side, ordered by how full
they are, so the volume about to become a problem is at the top rather than wherever it
happens to live. A pool the NAS does not report as healthy is raised above everything else.

**Storage → Pools** examines one box in detail: its pools, volumes and disks, with a degraded
pool explained in words and its unreadable slots named.

**Storage → Shares** lists the shared folders on a NAS. Opening one shows:

- **who may reach it** — each user or group, and whether that came from the user directly or
  from a group
- **its NFS export**, which is configured separately from those permissions and does not
  follow them. An export open to every host is highlighted, because file permissions will not
  save you there.

File and folder counts here are the NAS's **own cached figures** and can be hours stale. They
are labelled as such. For a live count, use a deep read in Monitoring.

**Storage → Files** browses a NAS as it sees itself. It is read-only: nothing on that page
copies, moves, renames, deletes or creates a share link.

---

## Monitoring

**Activity → NAS** shows what is watched on a NAS and what it last saw, grouped into pools,
volumes and shares. Anything not watched is listed at the bottom under **Unmonitored**,
because knowing what is *not* being read is part of reading the page.

Two buttons, which cover different things and never overwrite each other:

- **Read now** measures **pools and volumes** — pool status, capacity and free space — from
  the NAS's own API and again from `df` over SSH, so the two can disagree.
- **Deep read** measures **shares**, walking each with `du` and `find` for its true size and
  live file count, beside the counts the NAS keeps cached. On a large share this takes
  minutes.

Each group says which read fills it, and every measurement carries the moment it was taken.

**Click any measurement to see its history** — a chart of that figure over time, with the low,
the high, and the change across the range. The chart does not start at zero, deliberately: a
volume sitting at 91% all year would otherwise be a flat line, and the point is to make a few
percent visible. The range is always labelled.

A measurement marked **cached** is a figure the NAS computed earlier and hands back unchanged.
One marked **rounded** lost accuracy before NASQuay saw it — imported history, or a count that
could not read part of the tree. Neither is used by any rule.

**Activity → Clients** is the other half of the question: whether the machines that mount a
share still have it. A share can be perfectly healthy on the NAS while the machine that needs
it has silently lost the mount. Each machine is a tab, with a red count on the tab itself if
any of its mounts are down, and each mount's history is there the same way.

---

## Flags

A flag is NASQuay saying a rule fired: a volume losing space too quickly, a share losing
files, two measurements of the same thing disagreeing, a mount that has vanished, a pool
whose status changed.

They appear on the Dashboard and on the NAS page, with what was seen and when.

- **Acknowledge** records that somebody has looked.
- **Clear** closes it.

Clearing does not stop the rule. If the condition still holds, the next collection raises it
again — which is the point: a flag you dismiss without fixing comes back.

---

## Logs

**Activity → Logs** reads the NAS's own two logs. **Events** is what the system did; **Access**
is who reached what. Filter by severity, by period, or by a keyword in the message or the
resource. Any row opens to show everything else the NAS recorded about it.

The NAS records access as numbers with no explanation. NASQuay translates the ones it has
established — SMB, NFS, SSH/SFTP, HTTPS, and read, write, login, logout, login failed — and
shows anything else as a number rather than guessing.

One thing the log cannot tell you: **a failed key-based SSH login is never recorded.** An
absence of failures is not evidence that nothing was tried.

**Activity → Audit** is different — it is NASQuay's own record rather than the NAS's. Every
action anyone took through NASQuay, including the ones that were refused and why.

---

## The NAS itself

**System → Overview** is every box's condition at once: model, firmware, processor,
temperatures, memory, uptime, disks and any application with an update. Anything out of range
is lifted to the top — a NAS asking to be restarted, a temperature past the threshold the box
itself supplies, a failed fan, a disk too warm. Nothing here decides on its own what counts as
too hot; those thresholds come from the NAS.

**System → Accounts** shows the NAS's own users and groups, each user's effective permission
on every share and where it came from, and who is connected now. NFS carries no user name —
those sessions show a dash, because an NFS client is trusted by address, not by login.

**System → Security** shows what the NAS's own security applications report, including their
own wording when one is not installed. It is read-only: starting a scan changes the NAS.

---

## Using NASQuay from another AI tool

Any AI tool that speaks MCP can use NASQuay, if your role includes it. Make a token under
**API tokens** on your account panel, then point the tool at the address shown there —
NASQuay's own address followed by `/mcp` — with the header `Authorization: Bearer <token>`,
transport streamable HTTP.

- The token acts as **you**, and can never do more than your role allows.
- A **read only** token can look but change nothing. **Read and write** can change things.
  Destructive actions are refused unless an administrator made the token to allow them.
- The token is **shown once**. Copy it then; NASQuay keeps only a hash and cannot show it
  again. If it is lost or may have leaked, revoke it — anything using it stops at once.
- Every call is in the audit log under your name and the token's.

---

## Things NASQuay will not do

- **It never runs a free-form command.** SSH is limited to a fixed set of read-only
  measurements.
- **It checks permission before contacting a NAS**, not after.
- **A destructive action needs an explicit confirmation** from a person, and an unattended
  caller cannot perform one unless it has been explicitly allowed.
- **A tool nobody has reviewed can be run by nobody**, administrators included.
- **It does not hide what it could not read.** A count that skipped directories says so and is
  excluded from the rules, rather than being quietly short — because a silently short count
  looks exactly like files disappearing.
