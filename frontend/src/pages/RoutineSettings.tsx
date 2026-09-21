import { useEffect, useState } from "react";
import {
  api,
  type Provider,
  type Routine,
  type RoutineOperation,
  type RoutineRun,
  type RoutineStep,
  type User,
} from "../api";
import Help from "../components/Help";

// Routines: scheduled work that runs as a chosen user. Fixed routines are a list of
// steps; AI routines are a prompt, a provider and the operations the model may call.
//
// The server decides what is allowed — who may be the run-as user, which operations a
// routine may hold, whether destructive ones are permitted. This page only offers the
// choices and shows what the server said.

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

type Form = {
  name: string;
  description: string;
  kind: "fixed" | "ai";
  run_as_user_id: number;
  schedule_kind: Routine["schedule_kind"];
  interval_minutes: number;
  at_time: string;
  weekday: number;
  provider_id: number;
  prompt: string;
  steps: { op: string; nas: string; args: string }[];
  allowed: string[];
  allow_destructive: boolean;
  max_steps: number;
  timeout_s: number;
  alert_on: Routine["alert_on"];
};

const BLANK: Form = {
  name: "",
  description: "",
  kind: "ai",
  run_as_user_id: 0,
  schedule_kind: "manual",
  interval_minutes: 60,
  at_time: "07:00",
  weekday: 0,
  provider_id: 0,
  prompt: "",
  steps: [],
  allowed: [],
  allow_destructive: false,
  max_steps: 8,
  timeout_s: 600,
  alert_on: "failure",
};

const fromRoutine = (r: Routine): Form => ({
  name: r.name,
  description: r.description,
  kind: r.kind,
  run_as_user_id: r.run_as_user_id ?? 0,
  schedule_kind: r.schedule_kind,
  interval_minutes: r.interval_minutes,
  at_time: r.at_time,
  weekday: r.weekday,
  provider_id: r.provider_id ?? 0,
  prompt: r.prompt,
  steps: r.steps.map((s) => ({
    op: s.op,
    nas: s.nas,
    args: Object.keys(s.arguments).length ? JSON.stringify(s.arguments, null, 2) : "",
  })),
  allowed: r.allowed,
  allow_destructive: r.allow_destructive,
  max_steps: r.max_steps,
  timeout_s: r.timeout_s,
  alert_on: r.alert_on,
});

const schedule = (r: Routine) => {
  if (r.schedule_kind === "manual") return "run by hand";
  if (r.schedule_kind === "interval") return `every ${r.interval_minutes} min`;
  if (r.schedule_kind === "daily") return `daily at ${r.at_time}`;
  return `${WEEKDAYS[r.weekday]}s at ${r.at_time}`;
};

const statusClass = (value: string | null) =>
  value === "ok"
    ? "text-emerald-400"
    : value === "error"
      ? "text-red-400"
      : value === "running" || value === "queued"
        ? "text-amber-400"
        : "text-zinc-300";

// The form's steps become what the server takes. Arguments are JSON typed by hand; a
// step whose JSON does not parse stops the save and says which.
function toBody(form: Form): Record<string, unknown> {
  const steps: RoutineStep[] = form.steps.map((s, i) => {
    let args: Record<string, unknown> = {};
    if (s.args.trim()) {
      try {
        args = JSON.parse(s.args);
      } catch {
        throw new Error(`Step ${i + 1}: the arguments are not valid JSON`);
      }
    }
    return { op: s.op, nas: s.nas, arguments: args };
  });
  return {
    name: form.name,
    description: form.description,
    kind: form.kind,
    run_as_user_id: form.run_as_user_id,
    schedule_kind: form.schedule_kind,
    interval_minutes: form.interval_minutes,
    at_time: form.at_time,
    weekday: form.weekday,
    provider_id: form.provider_id || null,
    prompt: form.prompt,
    steps,
    allowed: form.allowed,
    allow_destructive: form.allow_destructive,
    max_steps: form.max_steps,
    timeout_s: form.timeout_s,
    alert_on: form.alert_on,
  };
}

export default function RoutineSettings() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [ops, setOps] = useState<RoutineOperation[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [history, setHistory] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.routines
      .list()
      .then(setRoutines)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load the routines"),
      );

  useEffect(() => {
    load();
    api.routines.operations().then(setOps).catch(() => setOps([]));
    // Only to offer choices; a role that cannot list these sees fewer of them.
    api.users.list().then(setUsers).catch(() => setUsers([]));
    api.providers.list().then(setProviders).catch(() => setProviders([]));
  }, []);

  // While anything is queued or running, keep the list current so the result appears
  // without a reload.
  const busy = routines.some((r) => r.last_status === "queued" || r.last_status === "running");
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(load, 5000);
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
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Routines</h2>
        <Help>
          <p>A routine is work NASQuay does by itself, as a chosen user, on a schedule or when you press <span className="text-zinc-200">Run now</span>.</p>
          <p><span className="text-zinc-200">Fixed</span> routines run a list of steps in order and stop at the first that fails. A notification step can include what the step before it returned by writing <span className="font-mono">{"{previous}"}</span> in its body.</p>
          <p><span className="text-zinc-200">AI</span> routines hand a prompt to a model along with the operations you tick, and the model decides what to call. It needs a provider that passed its tool-calling test.</p>
          <p>A routine runs <span className="text-zinc-200">as a user</span>, and can never do more than that user's role allows — and never more than its own list. You can only choose yourself, or a user whose role you could hand out.</p>
          <p><span className="text-zinc-200">Destructive</span> operations are refused unless the routine explicitly allows them, and only an administrator can allow that.</p>
          <p>The <span className="text-zinc-200">step limit</span> counts every call the model makes; the <span className="text-zinc-200">timeout</span> covers the whole run. Every call is in the audit log, and each run keeps what was called and what came back.</p>
          <p>Routines run in nasquay-worker. If the worker is stopped, a run stays queued.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      <div className="card space-y-3">
        <button
          className="w-full flex items-center gap-3 text-left"
          onClick={() => setAdding((was) => !was)}
        >
          <span className="text-zinc-300 w-3">{adding ? "▾" : "▸"}</span>
          <span className="text-sm">Add routine</span>
          <span className="text-xs text-zinc-300">a fixed list of steps, or a prompt for a model</span>
        </button>
        {adding && (
          <div className="border-t border-zinc-600 pt-3">
            <RoutineForm
              initial={BLANK}
              isNew
              ops={ops}
              users={users}
              providers={providers}
              onCancel={() => setAdding(false)}
              onSave={async (form) => {
                const ok = await act(
                  () => api.routines.create(toBody(form)),
                  `Added ${form.name} — press Run now to try it`,
                );
                if (ok) setAdding(false);
              }}
            />
          </div>
        )}
      </div>

      {routines.map((r) => (
        <div key={r.id} className="card space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm">{r.name}</span>
            <span className="text-xs text-zinc-300">
              {r.kind === "ai" ? `AI · ${r.provider_name ?? "no provider"}` : `fixed · ${r.steps.length} steps`}
              {" · "}
              {schedule(r)} · as {r.run_as_username ?? "nobody"}
            </span>
            {!r.enabled && <span className="text-xs text-amber-400">disabled</span>}
            {r.allow_destructive && <span className="text-xs text-red-400">destructive allowed</span>}
            {r.last_status && (
              <span className={`text-xs ${statusClass(r.last_status)}`}>
                {r.last_status} {r.last_finished_at ?? r.last_queued_at ?? ""}
              </span>
            )}
            <span className="flex gap-2 ml-auto">
              <button
                className="btn"
                disabled={r.last_status === "queued" || r.last_status === "running"}
                onClick={() => act(() => api.routines.run(r.id), `${r.name} queued`)}
              >
                Run now
              </button>
              <button
                className="btn"
                onClick={() =>
                  act(
                    () => api.routines.update(r.id, { enabled: !r.enabled }),
                    `${r.name} ${r.enabled ? "disabled" : "enabled"}`,
                  )
                }
              >
                {r.enabled ? "Disable" : "Enable"}
              </button>
              <button
                className="btn"
                onClick={() => setHistory((was) => (was === r.id ? null : r.id))}
              >
                {history === r.id ? "Hide runs" : "Runs"}
              </button>
              <button
                className="btn"
                onClick={() => setEditing((was) => (was === r.id ? null : r.id))}
              >
                {editing === r.id ? "Close" : "Edit"}
              </button>
              <button
                className="btn-danger"
                onClick={() => {
                  if (window.confirm(`Delete ${r.name} and its run history?`))
                    act(() => api.routines.remove(r.id), `Deleted ${r.name}`);
                }}
              >
                Delete
              </button>
            </span>
          </div>
          {r.description && <div className="text-xs text-zinc-300">{r.description}</div>}
          {r.last_status === "error" && r.last_error && (
            <div className="text-xs text-red-400">{r.last_error}</div>
          )}

          {history === r.id && <Runs routine={r} />}

          {editing === r.id && (
            <div className="border-t border-zinc-600 pt-3">
              <RoutineForm
                initial={fromRoutine(r)}
                isNew={false}
                ops={ops}
                users={users}
                providers={providers}
                onCancel={() => setEditing(null)}
                onSave={async (form) => {
                  const { kind: _kind, ...rest } = toBody(form);
                  const ok = await act(() => api.routines.update(r.id, rest), `Saved ${form.name}`);
                  if (ok) setEditing(null);
                }}
              />
            </div>
          )}
        </div>
      ))}

      {routines.length === 0 && (
        <div className="text-xs text-zinc-300">No routines yet.</div>
      )}
    </div>
  );
}

function Runs({ routine }: { routine: Routine }) {
  const [runs, setRuns] = useState<RoutineRun[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.routines
      .runs(routine.id)
      .then(setRuns)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the runs"));
  }, [routine.id, routine.last_status, routine.last_finished_at]);

  if (error) return <div className="text-xs text-red-400">{error}</div>;
  if (runs.length === 0) return <div className="text-xs text-zinc-300">No runs yet.</div>;

  return (
    <div className="border-t border-zinc-600 pt-2 space-y-1">
      {runs.map((run) => (
        <div key={run.id} className="text-xs">
          <button
            className="flex gap-3 w-full text-left hover:text-zinc-100"
            onClick={() => setOpen((was) => (was === run.id ? null : run.id))}
          >
            <span className="text-zinc-300 w-3">{open === run.id ? "▾" : "▸"}</span>
            <span className={statusClass(run.status)}>{run.status}</span>
            <span className="text-zinc-300">{run.started_at ?? run.queued_at}</span>
            <span className="text-zinc-300">{run.trigger}</span>
            <span className="text-zinc-300">{run.calls.length} calls</span>
          </button>
          {open === run.id && (
            <div className="pl-6 pt-1 space-y-2">
              {run.error && <div className="text-red-400">{run.error}</div>}
              {run.output && (
                <pre className="whitespace-pre-wrap text-zinc-100 font-mono">{run.output}</pre>
              )}
              {run.calls.map((c, i) => (
                <div key={i} className="font-mono">
                  <span className={c.ok ? "text-emerald-400" : "text-red-400"}>
                    {c.ok ? "ok" : "no"}
                  </span>{" "}
                  {c.op}
                  {c.nas ? ` on ${c.nas}` : ""}{" "}
                  <span className="text-zinc-300">{JSON.stringify(c.arguments)}</span>
                  <div className="text-zinc-300 break-all">{c.detail}</div>
                </div>
              ))}
              {run.alert && <div className="text-zinc-300">alert: {run.alert}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function RoutineForm({
  initial,
  isNew,
  ops,
  users,
  providers,
  onSave,
  onCancel,
}: {
  initial: Form;
  isNew: boolean;
  ops: RoutineOperation[];
  users: User[];
  providers: Provider[];
  onSave: (form: Form) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(initial);
  const [problem, setProblem] = useState("");
  const set = (change: Partial<Form>) => setForm((was) => ({ ...was, ...change }));
  const byId = Object.fromEntries(ops.map((op) => [op.id, op]));
  const offered = ops.filter((op) => form.allow_destructive || op.classification !== "destructive");

  const setStep = (index: number, change: Partial<Form["steps"][number]>) =>
    set({ steps: form.steps.map((s, i) => (i === index ? { ...s, ...change } : s)) });

  const toggle = (id: string) =>
    set({
      allowed: form.allowed.includes(id)
        ? form.allowed.filter((one) => one !== id)
        : [...form.allowed, id],
    });

  const save = () => {
    setProblem("");
    try {
      toBody(form);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "That cannot be saved");
      return;
    }
    onSave(form);
  };

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
            className="field w-40"
            value={form.kind}
            disabled={!isNew}
            onChange={(e) => set({ kind: e.target.value as Form["kind"] })}
          >
            <option value="ai">AI</option>
            <option value="fixed">Fixed steps</option>
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
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username} ({u.role_name})
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Alert</span>
          <select
            className="field w-40"
            value={form.alert_on}
            onChange={(e) => set({ alert_on: e.target.value as Form["alert_on"] })}
          >
            <option value="failure">when it fails</option>
            <option value="always">after every run</option>
            <option value="never">never</option>
          </select>
        </label>
      </div>

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
            onChange={(e) => set({ schedule_kind: e.target.value as Form["schedule_kind"] })}
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
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Timeout (s)</span>
          <input
            className="field w-24"
            type="number"
            min={30}
            max={3600}
            value={form.timeout_s}
            onChange={(e) => set({ timeout_s: Number(e.target.value) })}
          />
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.allow_destructive}
          onChange={(e) => set({ allow_destructive: e.target.checked })}
        />
        Allow destructive actions
        <span className="text-xs text-zinc-300">administrators only; off unless you mean it</span>
      </label>

      {form.kind === "ai" && (
        <div className="space-y-3">
          <div className="flex items-end gap-3 flex-wrap">
            <label className="space-y-1">
              <span className="text-xs text-zinc-300">Provider</span>
              <select
                className="field w-64"
                value={form.provider_id}
                onChange={(e) => set({ provider_id: Number(e.target.value) })}
              >
                <option value={0}>Choose a provider</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.model}
                    {p.tools_ok === true ? "" : p.tools_ok === false ? " (tools failed)" : " (tools untested)"}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs text-zinc-300">Step limit</span>
              <input
                className="field w-24"
                type="number"
                min={1}
                max={30}
                value={form.max_steps}
                onChange={(e) => set({ max_steps: Number(e.target.value) })}
              />
            </label>
          </div>
          <label className="space-y-1 block">
            <span className="text-xs text-zinc-300">Prompt</span>
            <textarea
              className="field h-28"
              placeholder="Check every NAS for open flags and shares over 90% full, and report anything that needs attention."
              value={form.prompt}
              onChange={(e) => set({ prompt: e.target.value })}
            />
          </label>
          <div className="space-y-1">
            <div className="text-xs text-zinc-300">
              What the model may call ({form.allowed.length} chosen). Its run-as user's role still
              decides at run time.
            </div>
            <div className="grid gap-x-4 gap-y-1 md:grid-cols-2 max-h-64 overflow-y-auto border border-zinc-600 p-2">
              {offered.map((op) => (
                <label key={op.id} className="flex items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={form.allowed.includes(op.id)}
                    onChange={() => toggle(op.id)}
                  />
                  <span>
                    <span className="font-mono text-zinc-100">{op.id}</span>
                    {op.classification !== "read" && (
                      <span
                        className={
                          op.classification === "destructive" ? " text-red-400" : " text-amber-400"
                        }
                      >
                        {" "}
                        {op.classification}
                      </span>
                    )}
                    <span className="block text-zinc-300">{op.description.slice(0, 120)}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}

      {form.kind === "fixed" && (
        <div className="space-y-2">
          {form.steps.map((step, i) => {
            const op = byId[step.op];
            return (
              <div key={i} className="border border-zinc-600 p-2 space-y-2">
                <div className="flex items-end gap-3 flex-wrap">
                  <span className="text-xs text-zinc-300 w-6">{i + 1}.</span>
                  <label className="space-y-1">
                    <span className="text-xs text-zinc-300">Operation</span>
                    <select
                      className="field w-72 font-mono text-xs"
                      value={step.op}
                      onChange={(e) => setStep(i, { op: e.target.value, nas: "" })}
                    >
                      <option value="">Choose</option>
                      {offered.map((one) => (
                        <option key={one.id} value={one.id}>
                          {one.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  {op?.needs_nas && (
                    <label className="space-y-1">
                      <span className="text-xs text-zinc-300">NAS</span>
                      <select
                        className="field w-40"
                        value={step.nas}
                        onChange={(e) => setStep(i, { nas: e.target.value })}
                      >
                        <option value="">Choose</option>
                        {op.nas_names.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <span className="flex gap-2 ml-auto">
                    <button
                      className="btn"
                      disabled={i === 0}
                      onClick={() => {
                        const steps = [...form.steps];
                        [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]];
                        set({ steps });
                      }}
                    >
                      Up
                    </button>
                    <button
                      className="btn"
                      onClick={() => set({ steps: form.steps.filter((_, j) => j !== i) })}
                    >
                      Remove
                    </button>
                  </span>
                </div>
                {op && <div className="text-xs text-zinc-300">{op.description.slice(0, 200)}</div>}
                <label className="space-y-1 block">
                  <span className="text-xs text-zinc-300">Arguments (JSON, optional)</span>
                  <textarea
                    className="field font-mono text-xs h-16"
                    placeholder={op?.id === "notify" ? '{"title": "Daily check", "body": "{previous}"}' : "{}"}
                    value={step.args}
                    onChange={(e) => setStep(i, { args: e.target.value })}
                  />
                </label>
              </div>
            );
          })}
          <button
            className="btn"
            disabled={form.steps.length >= 30}
            onClick={() => set({ steps: [...form.steps, { op: "", nas: "", args: "" }] })}
          >
            Add step
          </button>
        </div>
      )}

      {problem && <div className="text-sm text-red-400">{problem}</div>}
      <div className="flex gap-2">
        <button
          className="btn-primary"
          disabled={!form.name.trim() || !form.run_as_user_id}
          onClick={save}
        >
          {isNew ? "Add routine" : "Save"}
        </button>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
