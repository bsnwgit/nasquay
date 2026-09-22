import { useEffect, useState } from "react";
import { api, type Report, type ReportKind, type ReportRun } from "../api";
import Help from "../components/Help";

// Reports, in two places and one component. Under Activity it is the reading view: what
// has been produced, opened on the page or downloaded. Under Settings, with manage set,
// it also defines them.
//
// Every figure here was recorded earlier. Producing a report never contacts a NAS, which
// is why it can be run as often as anybody likes.

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const statusClass = (value: string | null) =>
  value === "ok"
    ? "text-emerald-400"
    : value === "error"
      ? "text-red-400"
      : value === "running" || value === "queued"
        ? "text-amber-400"
        : "text-zinc-300";

const schedule = (r: Report) => {
  if (r.schedule_kind === "manual") return "run by hand";
  if (r.schedule_kind === "interval") return `every ${r.interval_minutes} min`;
  if (r.schedule_kind === "daily") return `daily at ${r.at_time}`;
  return `${WEEKDAYS[r.weekday]}s at ${r.at_time}`;
};

export default function Reports({ manage = false }: { manage?: boolean }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [kinds, setKinds] = useState<ReportKind[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [list, produced] = await Promise.all([api.reports.list(), api.reports.runs()]);
      setReports(list);
      setRuns(produced);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the reports");
    }
  };

  useEffect(() => {
    load();
    api.reports.kinds().then(setKinds).catch(() => setKinds([]));
  }, []);

  // A queued report is produced within seconds, so the page keeps up on its own.
  const busy = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const act = async (what: () => Promise<unknown>, said: string) => {
    setError("");
    setNote("");
    try {
      await what();
      setNote(said);
      await load();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
      return false;
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Reports</h2>
        <Help>
          <p>A report says what has been happening, rather than that something is wrong now — that is what flags and notifications are for.</p>
          <p>Every figure comes from what NASQuay already recorded, so producing one never contacts a NAS and can be repeated as often as you like. A figure NASQuay does not have is shown as an em dash, never as zero.</p>
          <p>Four kinds: <span className="text-zinc-200">capacity</span> (how full, how fast, when full), <span className="text-zinc-200">change</span> (what moved), <span className="text-zinc-200">health</span> (flags, pools, mounts, collection) and <span className="text-zinc-200">activity</span> (what NASQuay did, and who asked).</p>
          <p>A report runs <span className="text-zinc-200">as a user</span> and shows only what that user's role may see. You can read one only if you could have run it as that user.</p>
          <p>Each is readable here, and downloadable as PDF or CSV. Delivery and how long reports are kept are settings.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      {manage && (
        <div className="card space-y-3">
          <button
            className="w-full flex items-center gap-3 text-left"
            onClick={() => setAdding((was) => !was)}
          >
            <span className="text-zinc-300 w-3">{adding ? "▾" : "▸"}</span>
            <span className="text-sm">Add report</span>
            <span className="text-xs text-zinc-300">one of the four kinds, on a schedule or by hand</span>
          </button>
          {adding && (
            <div className="border-t border-zinc-600 pt-3">
              <ReportForm
                kinds={kinds}
                isNew
                onCancel={() => setAdding(false)}
                onSave={async (body) => {
                  const ok = await act(
                    () => api.reports.create(body),
                    "Report added — press Produce now to see it",
                  );
                  if (ok) setAdding(false);
                }}
              />
            </div>
          )}
        </div>
      )}

      {/* The reports on the left, what they produced on the right: one is a list you
          maintain, the other a list you read, and stacking them buried the second. */}
      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <div className="space-y-4">
      {reports.map((report) => (
        <div key={report.id} className="card space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm">{report.name}</span>
            <span className="text-xs text-zinc-300">
              {report.kind} · {report.period_days} days · {report.nas_name ?? "every NAS"} ·{" "}
              {schedule(report)} · as {report.run_as_username ?? "nobody"}
            </span>
            {!report.enabled && <span className="text-xs text-amber-400">disabled</span>}
            {report.deliver && <span className="text-xs text-zinc-300">delivered</span>}
            {report.compare && <span className="text-xs text-zinc-300">compared</span>}
            {report.ai_summary && <span className="text-xs text-zinc-300">AI summary</span>}
            {report.last_status && (
              <span className={`text-xs ${statusClass(report.last_status)}`}>
                {report.last_status} {report.last_finished_at ?? ""}
              </span>
            )}
            <span className="flex gap-2 ml-auto">
              <button
                className="btn"
                disabled={report.last_status === "queued" || report.last_status === "running"}
                onClick={() => act(() => api.reports.run(report.id), `${report.name} queued`)}
              >
                Produce now
              </button>
              {report.last_ok_run && (
                <button className="btn" onClick={() => setOpen(report.last_ok_run)}>
                  Read the latest
                </button>
              )}
              {manage && (
                <>
                  <button
                    className="btn"
                    onClick={() =>
                      act(
                        () => api.reports.update(report.id, { enabled: !report.enabled }),
                        `${report.name} ${report.enabled ? "disabled" : "enabled"}`,
                      )
                    }
                  >
                    {report.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    className="btn"
                    onClick={() => setEditing((was) => (was === report.id ? null : report.id))}
                  >
                    {editing === report.id ? "Close" : "Edit"}
                  </button>
                  <button
                    className="btn-danger"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete ${report.name} and every report it produced? This cannot be undone.`,
                        )
                      )
                        act(() => api.reports.remove(report.id), `Deleted ${report.name}`);
                    }}
                  >
                    Delete
                  </button>
                </>
              )}
            </span>
          </div>
          {report.description && (
            <div className="text-xs text-zinc-300">{report.description}</div>
          )}
          {report.last_status === "error" && report.last_error && (
            <div className="text-xs text-red-400">{report.last_error}</div>
          )}
          {manage && editing === report.id && (
            <div className="border-t border-zinc-600 pt-3">
              <ReportForm
                kinds={kinds}
                isNew={false}
                initial={report}
                onCancel={() => setEditing(null)}
                onSave={async (body) => {
                  const ok = await act(
                    () => api.reports.update(report.id, body),
                    `Saved ${report.name}`,
                  );
                  if (ok) setEditing(null);
                }}
              />
            </div>
          )}
        </div>
      ))}

      {reports.length === 0 && (
        <div className="card text-xs text-zinc-300">
          No reports yet{manage ? "." : " — an administrator defines them."}
        </div>
      )}
        </div>

        <div className="card space-y-2">
        <div className="text-xs uppercase tracking-wide text-zinc-300">Produced</div>
        {runs.length === 0 && (
          <div className="text-xs text-zinc-300">Nothing produced yet.</div>
        )}
        {runs.map((run) => (
          <div key={run.id} className="flex items-center gap-3 flex-wrap text-xs border-t
                                       border-zinc-600/60 pt-2 first:border-0">
            <span className={statusClass(run.status)}>{run.status}</span>
            <span className="text-zinc-100">{run.report_name}</span>
            <span className="text-zinc-300">{run.kind}</span>
            <span className="text-zinc-300">{run.finished_at ?? run.queued_at}</span>
            <span className="text-zinc-300">{run.trigger}</span>
            {run.error && <span className="text-red-400">{run.error}</span>}
            {run.delivered && <span className="text-zinc-300">sent: {run.delivered}</span>}
            {run.status === "ok" && (
              <span className="flex gap-2 ml-auto">
                <button className="btn" onClick={() => setOpen(run.id)}>
                  Read
                </button>
                <button className="btn" onClick={() => api.reports.download(run.id, "pdf")}>
                  PDF
                </button>
                <button className="btn" onClick={() => api.reports.download(run.id, "csv")}>
                  CSV
                </button>
              </span>
            )}
          </div>
        ))}
        </div>
      </div>

      {open !== null && <ReportView runId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function ReportView({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [run, setRun] = useState<ReportRun | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.reports
      .read(runId)
      .then(setRun)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not open it"));
  }, [runId]);

  const figures = run?.figures;

  return (
    <div className="fixed inset-0 z-10 bg-black/60 p-4 overflow-y-auto" onClick={onClose}>
      <div
        className="mx-auto max-w-6xl bg-zinc-950 border border-zinc-600 p-4 space-y-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-sm text-zinc-100">{figures?.title ?? "Report"}</h2>
          {figures && (
            <span className="text-xs text-zinc-300">
              the past {figures.period?.days} days · generated {figures.generated_at} ·{" "}
              {figures.nas}
            </span>
          )}
          <span className="flex gap-2 ml-auto">
            <button className="btn" onClick={() => api.reports.download(runId, "pdf")}>
              PDF
            </button>
            <button className="btn" onClick={() => api.reports.download(runId, "csv")}>
              CSV
            </button>
            <button className="btn" onClick={onClose}>
              Close
            </button>
          </span>
        </div>

        {error && <div className="text-sm text-red-400">{error}</div>}
        {!run && !error && <div className="text-sm text-zinc-300">Opening…</div>}

        {figures?.summary && (
          <div className="border border-amber-500/40 p-3 space-y-1">
            <div className="text-xs uppercase tracking-wide text-amber-400">Summary</div>
            <div className="text-xs text-zinc-300">
              Written by a language model from the figures below. The figures are the report.
            </div>
            <div className="text-sm text-zinc-100 whitespace-pre-wrap">{figures.summary}</div>
          </div>
        )}

        {(figures?.sections ?? []).map((section, i) => (
          <div key={i} className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-zinc-300">{section.heading}</div>
            {section.note && <div className="text-xs text-zinc-300">{section.note}</div>}
            {section.rows.length === 0 ? (
              <div className="text-xs text-zinc-300">Nothing to report.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-zinc-300 border-b border-zinc-600">
                      {section.columns.map((column, c) => (
                        <th key={c} className="py-1 pr-3 font-normal">
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {section.rows.map((row, r) => (
                      <tr key={r} className="border-b border-zinc-600/40">
                        {row.map((value, c) => (
                          <td key={c} className="py-1 pr-3 text-zinc-100 align-top">
                            {String(value)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportForm({
  kinds,
  isNew,
  initial,
  onSave,
  onCancel,
}: {
  kinds: ReportKind[];
  isNew: boolean;
  initial?: Report;
  onSave: (body: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    kind: initial?.kind ?? "capacity",
    period_days: initial?.period_days ?? 30,
    nas_id: initial?.nas_id ?? 0,
    schedule_kind: initial?.schedule_kind ?? "manual",
    interval_minutes: initial?.interval_minutes ?? 1440,
    at_time: initial?.at_time ?? "07:00",
    weekday: initial?.weekday ?? 0,
    run_as_user_id: initial?.run_as_user_id ?? 0,
    deliver: initial?.deliver ?? false,
    ai_summary: initial?.ai_summary ?? false,
    compare: initial?.compare ?? false,
    provider_id: initial?.provider_id ?? 0,
  });
  const [users, setUsers] = useState<{ id: number; username: string; role_name: string }[]>([]);
  const [units, setUnits] = useState<{ id: number; name: string }[]>([]);
  const [providers, setProviders] = useState<{ id: number; name: string; model: string }[]>([]);
  const set = (change: Partial<typeof form>) => setForm((was) => ({ ...was, ...change }));

  useEffect(() => {
    api.users.list().then(setUsers).catch(() => setUsers([]));
    api.nas.list().then(setUnits).catch(() => setUnits([]));
    api.providers.list().then(setProviders).catch(() => setProviders([]));
  }, []);

  const chosen = kinds.find((one) => one.kind === form.kind);

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-3 flex-wrap">
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Name</span>
          <input
            className="field w-56"
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Kind</span>
          <select
            className="field w-44"
            value={form.kind}
            onChange={(e) => set({ kind: e.target.value as Report["kind"] })}
          >
            {kinds.map((one) => (
              <option key={one.kind} value={one.kind}>
                {one.title}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Period (days)</span>
          <input
            className="field w-24"
            type="number"
            min={1}
            max={3650}
            value={form.period_days}
            onChange={(e) => set({ period_days: Number(e.target.value) })}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">NAS</span>
          <select
            className="field w-44"
            value={form.nas_id}
            onChange={(e) => set({ nas_id: Number(e.target.value) })}
          >
            <option value={0}>every NAS</option>
            {units.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Runs as</span>
          <select
            className="field w-48"
            value={form.run_as_user_id}
            onChange={(e) => set({ run_as_user_id: Number(e.target.value) })}
          >
            <option value={0}>Choose a user</option>
            {users.map((one) => (
              <option key={one.id} value={one.id}>
                {one.username} ({one.role_name})
              </option>
            ))}
          </select>
        </label>
      </div>

      {chosen && <div className="text-xs text-zinc-300">{chosen.description}</div>}

      <label className="space-y-1 block">
        <span className="text-xs text-zinc-300">Description</span>
        <input
          className="field"
          value={form.description}
          onChange={(e) => set({ description: e.target.value })}
        />
      </label>

      <div className="flex items-end gap-3 flex-wrap">
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Schedule</span>
          <select
            className="field w-40"
            value={form.schedule_kind}
            onChange={(e) => set({ schedule_kind: e.target.value as Report["schedule_kind"] })}
          >
            <option value="manual">By hand only</option>
            <option value="interval">Every N minutes</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </label>
        {form.schedule_kind === "interval" && (
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Minutes</span>
            <input
              className="field w-24"
              type="number"
              min={5}
              max={10080}
              value={form.interval_minutes}
              onChange={(e) => set({ interval_minutes: Number(e.target.value) })}
            />
          </label>
        )}
        {form.schedule_kind === "weekly" && (
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Day</span>
            <select
              className="field w-36"
              value={form.weekday}
              onChange={(e) => set({ weekday: Number(e.target.value) })}
            >
              {WEEKDAYS.map((day, i) => (
                <option key={day} value={i}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        )}
        {(form.schedule_kind === "daily" || form.schedule_kind === "weekly") && (
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">At (HH:MM)</span>
            <input
              className="field w-24 font-mono"
              value={form.at_time}
              onChange={(e) => set({ at_time: e.target.value })}
            />
          </label>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.compare}
          onChange={(e) => set({ compare: e.target.checked })}
        />
        Compare with the period before
        <span className="text-xs text-zinc-300">
          the same figures over the {form.period_days} days before this period, so growth reads
          as faster or slower rather than merely large
        </span>
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.deliver}
          onChange={(e) => set({ deliver: e.target.checked })}
        />
        Send it when it is produced
        <span className="text-xs text-zinc-300">
          on the notification channels; attachment or link is a setting
        </span>
      </label>

      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.ai_summary}
            onChange={(e) => set({ ai_summary: e.target.checked })}
          />
          Add a summary in words
        </label>
        {form.ai_summary && (
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Provider</span>
            <select
              className="field w-64"
              value={form.provider_id}
              onChange={(e) => set({ provider_id: Number(e.target.value) })}
            >
              <option value={0}>Choose a provider</option>
              {providers.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name} · {one.model}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="flex gap-2">
        <button
          className="btn-primary"
          disabled={!form.name.trim() || !form.run_as_user_id}
          onClick={() =>
            onSave({ ...form, nas_id: form.nas_id || null, provider_id: form.provider_id || null })
          }
        >
          {isNew ? "Add report" : "Save"}
        </button>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
