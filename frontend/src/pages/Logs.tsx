import { Fragment, useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";

// QuLog's two logs, read through list_event_logs and list_access_logs. Both take the same
// filters: a severity bitmask, a keyword, and a date range whose relative form is a plain
// "-N" meaning N days ago ("-1" is the last 24 hours, "-0" no lower bound at all).

const PAGE = 50;

// Only the fields the table lays out are named. The rest — QNAP's numeric action and
// actionResult among them — are shown as they arrive when a row is opened, because a code
// nobody here can decode is still better than hiding the only thing that explains a
// warning.
type Entry = {
  id?: number;
  date?: string;
  time?: string;
  level?: number;
  user?: string;
  ip?: string;
  computer?: string;
  application?: string;
  clientApp?: string;
  message?: string;
  resource?: string;
  [field: string]: unknown;
};

const LAID_OUT = ["id", "date", "time", "level", "user", "ip", "application", "clientApp",
                  "message", "resource", "computer", "service", "action"];

// The access log carries numbers where QuLog Center shows words, and QNAP publishes no key.
// These were derived by exporting QuLog's own CSV and joining it to the same rows read over
// MCP on date, time, user, address and resource: 2,000 of 2,000 rows matched, so these are
// read off the NAS's own labelling rather than guessed. NFS is from a second NAS, whose rows
// name the protocol in clientApp. A code not in either table is shown as a number.
const SERVICES: Record<number, string> = {
  1: "SMB",
  8: "NFS",
  64: "SSH/SFTP",
  1024: "HTTPS",
};

const ACTIONS: Record<number, string> = {
  2: "read",
  4: "write",
  16: "create directory",
  256: "login failed",
  512: "login",
  1024: "logout",
  16384: "add",
};

// The NAS writes "---" where it has nothing, in any field.
const blank = (value: unknown) => value === undefined || value === null || value === "" ||
  value === "---";

const show = (value: unknown) => (blank(value) ? "—" : String(value));

type Answer = {
  logs?: Entry[];
  total?: number;
  severity?: { info?: number; warn?: number; error?: number };
};

const KINDS = [
  { key: "events", tool: "list_event_logs", label: "Events", search: "message" },
  { key: "access", tool: "list_access_logs", label: "Access", search: "resource" },
] as const;

const SEVERITIES = [
  { mask: 7, label: "All" },
  { mask: 1, label: "Information" },
  { mask: 2, label: "Warning" },
  { mask: 4, label: "Error" },
];

const SINCE = [
  { value: "-1", label: "24 hours" },
  { value: "-7", label: "7 days" },
  { value: "-30", label: "30 days" },
  { value: "-0", label: "Everything" },
];

const LEVELS: Record<number, { label: string; tone: string }> = {
  1: { label: "info", tone: "text-zinc-500" },
  2: { label: "warning", tone: "text-amber-400" },
  4: { label: "error", tone: "text-red-400" },
};

export default function Logs() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [kind, setKind] = useState<(typeof KINDS)[number]>(KINDS[0]);
  const [severity, setSeverity] = useState(7);
  const [since, setSince] = useState("-1");
  const [keyword, setKeyword] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [answer, setAnswer] = useState<Answer>({});
  const [opened, setOpened] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.nas
      .list()
      .then((list) => {
        const enabled = list.filter((n) => n.enabled);
        setUnits(enabled);
        if (enabled.length && selected === null) setSelected(enabled[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"));
  }, []);

  const nasName = units.find((n) => n.id === selected)?.name ?? "the NAS";

  useEffect(() => {
    if (selected === null) return;
    let current = true;
    setBusy(`Reading the ${kind.label.toLowerCase()} log on ${nasName}`);
    setError("");

    const args: Record<string, unknown> = { limit: PAGE, page, level2s: severity };
    // "-0" means no lower bound, which the NAS expresses by the filter being absent.
    if (since !== "-0") args.date_begin = since;
    if (applied) args[kind.search] = applied;

    api
      .run(selected, kind.tool, args)
      .then((result) => {
        if (!current) return;
        const data = (result.json_result ?? {}) as Answer;
        setAnswer(data);
        setEntries(data.logs ?? []);
      })
      .catch((err) => {
        if (!current) return;
        setEntries([]);
        setAnswer({});
        setError(err instanceof Error ? err.message : "Could not read the log");
      })
      .finally(() => current && setBusy(""));
    return () => {
      current = false;
    };
  }, [selected, kind, severity, since, applied, page, units]);

  const change = (apply: () => void) => {
    setPage(1);
    apply();
  };

  const total = answer.total ?? 0;
  const shown = (page - 1) * PAGE + entries.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-400">Logs</h1>
        {units.map((nas) => (
          <button
            key={nas.id}
            onClick={() => change(() => setSelected(nas.id))}
            className={
              nas.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-700 text-zinc-300 hover:border-zinc-500"
            }
          >
            {nas.name}
          </button>
        ))}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {units.length === 0 && <div className="card text-sm text-zinc-500">No enabled NAS units.</div>}

      {units.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap text-sm">
          {KINDS.map((one) => (
            <button
              key={one.key}
              onClick={() => change(() => setKind(one))}
              className={
                one.key === kind.key
                  ? "px-3 py-1 border border-amber-500 text-amber-400"
                  : "px-3 py-1 border border-zinc-700 text-zinc-300 hover:border-zinc-500"
              }
            >
              {one.label}
            </button>
          ))}

          <span className="w-px h-5 bg-zinc-800 mx-1" />

          {SEVERITIES.map((one) => (
            <button
              key={one.mask}
              onClick={() => change(() => setSeverity(one.mask))}
              className={
                one.mask === severity
                  ? "px-2 py-1 text-xs border border-amber-500 text-amber-400"
                  : "px-2 py-1 text-xs border border-zinc-800 text-zinc-400 hover:border-zinc-600"
              }
            >
              {one.label}
            </button>
          ))}

          <span className="w-px h-5 bg-zinc-800 mx-1" />

          {SINCE.map((one) => (
            <button
              key={one.value}
              onClick={() => change(() => setSince(one.value))}
              className={
                one.value === since
                  ? "px-2 py-1 text-xs border border-amber-500 text-amber-400"
                  : "px-2 py-1 text-xs border border-zinc-800 text-zinc-400 hover:border-zinc-600"
              }
            >
              {one.label}
            </button>
          ))}

          <form
            className="flex items-center gap-2 ml-auto"
            onSubmit={(event) => {
              event.preventDefault();
              change(() => setApplied(keyword.trim()));
            }}
          >
            <input
              className="field w-56"
              placeholder={kind.key === "access" ? "Search the resource" : "Search the message"}
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
            />
            <button className="btn" type="submit">
              Search
            </button>
            {applied && (
              <button
                className="btn"
                type="button"
                onClick={() => change(() => { setKeyword(""); setApplied(""); })}
              >
                Clear
              </button>
            )}
          </form>
        </div>
      )}

      {!busy && !error && answer.severity && (
        <div className="flex items-center gap-4 text-xs text-zinc-500">
          <span>{total} entries match</span>
          <span className="text-zinc-500">{answer.severity.info ?? 0} information</span>
          <span className="text-amber-400">{answer.severity.warn ?? 0} warning</span>
          <span className="text-red-400">{answer.severity.error ?? 0} error</span>
        </div>
      )}

      {busy && <Busy label={busy} />}

      {!busy && !error && units.length > 0 && (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="th whitespace-nowrap">When</th>
                <th className="th">Level</th>
                <th className="th">{kind.key === "access" ? "Protocol" : "Application"}</th>
                {kind.key === "access" && <th className="th">Action</th>}
                <th className="th">User</th>
                <th className="th">From</th>
                <th className="th">{kind.key === "access" ? "Resource" : "Message"}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const level = LEVELS[entry.level ?? 1] ?? { label: String(entry.level), tone: "text-zinc-500" };
                const expanded = opened === entry.id;
                const rest = Object.entries(entry).filter(
                  ([field, value]) => !LAID_OUT.includes(field) && !blank(value),
                );
                return (
                  <Fragment key={entry.id}>
                    <tr
                      className="hover:bg-zinc-900/60 cursor-pointer"
                      onClick={() => setOpened(expanded ? null : entry.id ?? null)}
                    >
                      <td className="td text-zinc-400 whitespace-nowrap">
                        <span className="text-zinc-600 mr-2">{expanded ? "▾" : "▸"}</span>
                        {entry.date} {entry.time}
                      </td>
                      <td className={`td whitespace-nowrap ${level.tone}`}>{level.label}</td>
                      <td className="td text-zinc-400 whitespace-nowrap">
                        {kind.key === "access"
                          ? SERVICES[entry.service as number] ??
                            (blank(entry.clientApp) ? show(entry.service) : String(entry.clientApp))
                          : show(entry.application)}
                      </td>
                      {kind.key === "access" && (
                        <td
                          className={`td whitespace-nowrap ${
                            entry.action === 256 ? "text-red-400" : "text-zinc-400"
                          }`}
                        >
                          {ACTIONS[entry.action as number] ?? show(entry.action)}
                        </td>
                      )}
                      <td className="td text-zinc-400 whitespace-nowrap">{show(entry.user)}</td>
                      <td className="td text-zinc-500 whitespace-nowrap">{show(entry.ip)}</td>
                      <td className="td text-zinc-300 break-all">
                        {show(kind.key === "access" ? entry.resource : entry.message)}
                      </td>
                    </tr>
                    {expanded && (
                      <tr>
                        <td className="td text-xs text-zinc-500" colSpan={kind.key === "access" ? 7 : 6}>
                          <div className="flex flex-wrap gap-x-6 gap-y-1">
                            {!blank(entry.message) && kind.key === "access" && (
                              <span className="text-zinc-300">{String(entry.message)}</span>
                            )}
                            {!blank(entry.computer) && <span>computer {String(entry.computer)}</span>}
                            {rest.map(([field, value]) => (
                              <span key={field}>
                                {field} {String(value)}
                              </span>
                            ))}
                            {rest.length === 0 && blank(entry.message) && (
                              <span>The NAS recorded nothing else about this entry.</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {entries.length === 0 && (
                <tr>
                  <td className="td text-zinc-500" colSpan={kind.key === "access" ? 7 : 6}>
                    Nothing matches.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {!busy && !error && total > PAGE && (
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <button className="btn" disabled={shown >= total} onClick={() => setPage(page + 1)}>
            Next
          </button>
          <span>
            {(page - 1) * PAGE + 1}–{shown} of {total}
          </span>
        </div>
      )}
    </div>
  );
}
