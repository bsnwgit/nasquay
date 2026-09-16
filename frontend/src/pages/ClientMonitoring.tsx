import { useEffect, useState } from "react";
import { api, type Client, type Nas, type Reading, type Target } from "../api";
import Busy from "../components/Busy";
import Trouble from "../components/Trouble";
import Help from "../components/Help";
import Series from "../components/Series";
import { bytes, when } from "../utils/format";

// What the machines that mount a share can see, over time.
//
// Kept apart from the NAS readings on purpose: these answer a different question. A NAS
// can be entirely healthy while the machine that needs it has lost the mount, and that is
// the failure this page exists to make visible.

const value = (reading: Reading) => {
  if (reading.value === null) return "—";
  if (reading.metric === "client_mounted") return reading.value ? "mounted" : "not mounted";
  return reading.metric.endsWith("_bytes") ? bytes(reading.value) : reading.value.toLocaleString();
};

export default function ClientMonitoring() {
  const [clients, setClients] = useState<Client[]>([]);
  const [units, setUnits] = useState<Nas[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [readings, setReadings] = useState<Reading[]>([]);
  const [history, setHistory] = useState<{ key: string; readings: Reading[] } | null>(null);
  // One machine at a time, chosen the same way a NAS is chosen elsewhere.
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState("Loading");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    const [clientList, nasList, found, taken] = await Promise.allSettled([
      api.clients.list(),
      api.nas.list(),
      api.monitoring.targets(),
      api.monitoring.readings({ limit: 1000 }),
    ]);
    if (clientList.status === "fulfilled") {
      setClients(clientList.value);
      if (clientList.value.length) {
        setSelected((current) => current ?? clientList.value[0].id);
      }
    }
    if (nasList.status === "fulfilled") setUnits(nasList.value);
    if (found.status === "fulfilled") setTargets(found.value);
    else setError(found.reason instanceof Error ? found.reason.message : "Could not load");
    if (taken.status === "fulfilled") setReadings(taken.value);
  };

  useEffect(() => {
    load().finally(() => setBusy(""));
  }, []);

  const mounts = targets.filter((one) => one.kind === "client_mount");

  // A mount is read as part of its NAS's fast pass, so reading them means reading each NAS
  // that owns one — there is no separate collection for clients.
  const readAll = async () => {
    const owners = [...new Set(mounts.filter((one) => one.enabled).map((one) => one.nas_id))];
    if (!owners.length) return;
    setBusy("Asking each client what it has mounted");
    setError("");
    setNote("");
    try {
      const results = await Promise.allSettled(
        owners.map((id) => api.monitoring.collect(id, "client")),
      );
      const problems = results.flatMap((one) =>
        one.status === "fulfilled"
          ? one.value.problems
          : [one.reason instanceof Error ? one.reason.message : "could not be read"],
      );
      if (problems.length) setError(problems.join(" · "));
      else setNote("Read");
      await load();
    } finally {
      setBusy("");
    }
  };

  const openHistory = async (target: Target, metric: string) => {
    const key = `${target.id}:${metric}`;
    if (history?.key === key) {
      setHistory(null);
      return;
    }
    setHistory({ key, readings: [] });
    try {
      const series = await api.monitoring.readings({ target_id: target.id, metric, limit: 500 });
      setHistory({ key, readings: series });
    } catch (err) {
      setHistory(null);
      setError(err instanceof Error ? err.message : "Could not read that history");
    }
  };

  const latest = new Map<number, Reading[]>();
  for (const reading of readings) {
    const list = latest.get(reading.target_id) ?? [];
    if (!list.some((one) => one.metric === reading.metric)) list.push(reading);
    latest.set(reading.target_id, list);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Clients</h1>
        <Help>
          <p>What the machines that mount a share can see, and what they saw before.</p>
          <p>This is a different question from the NAS readings. A NAS can be perfectly healthy while the machine that needs it has silently lost the mount — which has happened here — and nothing on the NAS side would show it.</p>
          <p>A mount is read as part of its NAS's fast pass, so reading here reads each NAS that owns a watched mount. Mounts are added under Settings → Monitoring → Clients.</p>
          <p>Click any measurement to see its history. <span className="text-zinc-200">mounted</span> is recorded every pass, so a mount that dropped and came back shows as exactly that.</p>
        </Help>
        {clients.map((one) => {
          const theirs = mounts.filter((m) => m.client_id === one.id);
          const down = theirs.filter((m) => {
            const up = (latest.get(m.id) ?? []).find((r) => r.metric === "client_mounted");
            return up !== undefined && !up.value;
          }).length;
          return (
            <button
              key={one.id}
              onClick={() => setSelected(one.id)}
              className={
                one.id === selected
                  ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                  : "px-3 py-1 text-sm border border-zinc-600 text-zinc-200 hover:border-zinc-500"
              }
            >
              {one.name}
              {/* A machine with a dropped mount says so on its own tab, so the state is not
                  hidden behind choosing it. */}
              {down > 0 && <span className="text-red-400"> ·{down}</span>}
            </button>
          );
        })}
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-zinc-300">{note}</span>}
      </div>

      {mounts.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <button className="btn" onClick={readAll} disabled={!!busy}>
            Read now
          </button>
        </div>
      )}

      <Trouble only="client" />

      {busy && <Busy label={busy} />}

      {!busy && selected !== null && mounts.filter((one) => one.client_id === selected).length === 0 && (
        <div className="card text-sm text-zinc-300">
          Nothing is watched on this machine yet. Add its mounts under Settings → Monitoring →
          Clients.
        </div>
      )}

      {!busy && clients.length === 0 && (
        <div className="card text-sm text-zinc-300">
          No client mounts are being watched. Add a machine and its mounts under Settings →
          Monitoring → Clients.
        </div>
      )}

      {!busy &&
        clients
          .filter((client) => client.id === selected)
          .map((client) => {
          const mine = mounts.filter((one) => one.client_id === client.id);
          return (
            <div key={client.id} className="space-y-2">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-xs text-zinc-300">
                  {client.ssh_user}@{client.address}
                </span>
                <span className="text-xs text-zinc-300">
                  {mine.length} {mine.length === 1 ? "mount" : "mounts"}
                </span>
                {client.last_checked_at && (
                  <span className="text-xs text-zinc-300">
                    last tested {when(client.last_checked_at)}
                  </span>
                )}
              </div>

              {mine.map((target) => {
                const seen = latest.get(target.id) ?? [];
                const up = seen.find((one) => one.metric === "client_mounted");
                return (
                  <div key={target.id} className="card space-y-2">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span
                        className={
                          up === undefined
                            ? "h-2 w-2 bg-zinc-600 shrink-0"
                            : up.value
                              ? "h-2 w-2 bg-emerald-400 shrink-0"
                              : "h-2 w-2 bg-red-500 shrink-0"
                        }
                      />
                      <span className="text-sm">{target.ref}</span>
                      <span className="text-xs text-zinc-300">
                        {units.find((one) => one.id === target.nas_id)?.name} ·{" "}
                        {target.parent_ref || "share not recorded"}
                      </span>
                      {!target.enabled && (
                        <span className="text-xs text-zinc-300">not watched</span>
                      )}
                      <span
                        className={
                          up === undefined
                            ? "text-xs text-zinc-300 ml-auto"
                            : up.value
                              ? "text-xs text-emerald-400 ml-auto"
                              : "text-xs text-red-400 ml-auto"
                        }
                      >
                        {up === undefined
                          ? "never read"
                          : `${up.value ? "mounted" : "NOT MOUNTED"} · ${when(up.taken_at)}`}
                      </span>
                    </div>

                    {seen.length > 0 && (
                      <div className="grid md:grid-cols-2 gap-x-12">
                        {seen.map((reading) => {
                          const key = `${target.id}:${reading.metric}`;
                          const open = history?.key === key;
                          return (
                            <button
                              key={reading.metric}
                              onClick={() => openHistory(target, reading.metric)}
                              title="Show this measurement's history"
                              className={
                                "flex items-center gap-2 text-xs py-0.5 border-b text-left w-full " +
                                (open
                                  ? "border-amber-500/40 text-amber-400"
                                  : "border-zinc-600/40 hover:border-zinc-600")
                              }
                            >
                              <span className={open ? "flex-1" : "text-zinc-300 flex-1"}>
                                {reading.metric}
                              </span>
                              <span className={open ? "" : "text-zinc-200"}>{value(reading)}</span>
                              <span className="text-zinc-300">
                                {when(reading.taken_at).slice(5, 16)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {history && history.key.startsWith(`${target.id}:`) && (
                      <div className="border-t border-zinc-600 pt-3 space-y-2">
                        <div className="text-xs text-zinc-200">
                          {history.key.split(":")[1]} on {target.ref}
                        </div>
                        <Series
                          readings={history.readings}
                          format={(figure) =>
                            history.key.endsWith("_bytes")
                              ? bytes(figure)
                              : history.key.endsWith("client_mounted")
                                ? figure
                                  ? "mounted"
                                  : "not mounted"
                                : figure.toLocaleString()
                          }
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
    </div>
  );
}
