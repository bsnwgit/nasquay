import { useEffect, useState } from "react";
import { api, type Flag, type Nas, type Reading, type Target } from "../api";
import Busy from "../components/Busy";
import { bytes, when } from "../utils/format";
import Help from "../components/Help";
import Series from "../components/Series";

// What NASQuay watches on one NAS, and what it last saw. Discovery asks the NAS what
// exists; collection takes a set of readings now. Both are ordinary actions, so a role
// that may look but not collect simply finds the buttons refuse.
//
// There is no schedule yet — that belongs to the worker, which does not exist. Everything
// here is taken because somebody asked for it.

// Bytes where the metric is bytes, a plain count otherwise.
const value = (reading: Reading) => {
  if (reading.value === null) return "—";
  return reading.metric.endsWith("_bytes") ? bytes(reading.value) : reading.value.toLocaleString();
};

// Which read fills which kind of target. The two never overlap: a fast read never touches
// a share, a deep read never touches a pool or a volume.
const GROUPS: { kind: string; title: string; filled: string }[] = [
  { kind: "pool", title: "Pools", filled: "Read now" },
  { kind: "volume", title: "Volumes", filled: "Read now" },
  { kind: "share", title: "Shares", filled: "Deep read" },
  { kind: "client_mount", title: "Client mounts", filled: "Read now" },
];

export default function Monitoring() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [readings, setReadings] = useState<Reading[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [busy, setBusy] = useState("");
  // Which read is running, so its button shows as the active one.
  const [running, setRunning] = useState("");
  // Which metric's history is open, and what came back for it.
  const [history, setHistory] = useState<{ key: string; readings: Reading[] } | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    const [found, taken, open] = await Promise.allSettled([
      api.monitoring.targets(),
      api.monitoring.readings({ limit: 1000 }),
      api.monitoring.flags(),
    ]);
    if (found.status === "fulfilled") setTargets(found.value);
    else setError(found.reason instanceof Error ? found.reason.message : "Could not load targets");
    if (taken.status === "fulfilled") setReadings(taken.value);
    if (open.status === "fulfilled") setFlags(open.value);
  };

  useEffect(() => {
    setBusy("Loading what is watched");
    api.nas
      .list()
      .then((list) => {
        const enabled = list.filter((n) => n.enabled);
        setUnits(enabled);
        if (enabled.length) setSelected((current) => current ?? enabled[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"));
    load().finally(() => setBusy(""));
  }, []);

  const nas = units.find((n) => n.id === selected);


  const collect = async (tier: string) => {
    if (!nas) return;
    setRunning(tier);
    setBusy(
      tier === "slow"
        ? `Walking every watched share on ${nas.name} — this can take minutes`
        : `Taking readings from ${nas.name}`,
    );
    setError("");
    setNote("");
    try {
      const result = await api.monitoring.collect(nas.id, tier);
      setNote(
        `${result.readings} readings` +
          (result.problems.length ? ` — ${result.problems.join(" · ")}` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collection failed");
    } finally {
      setBusy("");
      setRunning("");
    }
  };


  const openHistory = async (target: Target, metric: string) => {
    const key = `${target.id}:${metric}`;
    if (history?.key === key) {
      setHistory(null);
      return;
    }
    setHistoryBusy(true);
    setHistory({ key, readings: [] });
    try {
      const series = await api.monitoring.readings({ target_id: target.id, metric, limit: 500 });
      setHistory({ key, readings: series });
    } catch (err) {
      setHistory(null);
      setError(err instanceof Error ? err.message : "Could not read that history");
    } finally {
      setHistoryBusy(false);
    }
  };

  // The most recent reading of each metric, per target.
  const latest = new Map<number, Reading[]>();
  for (const reading of readings) {
    const list = latest.get(reading.target_id) ?? [];
    if (!list.some((one) => one.metric === reading.metric)) list.push(reading);
    latest.set(reading.target_id, list);
  }

  const settle = async (flag: Flag, clear: boolean) => {
    try {
      await api.monitoring.acknowledge(flag.id, clear);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update that flag");
    }
  };

  const raised = flags.filter((flag) => flag.nas_id === selected);
  const mine = targets.filter((target) => target.nas_id === selected);
  const watching = mine.filter((target) => target.enabled);
  const ignored = mine.filter((target) => !target.enabled);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Monitoring</h1>
        <Help>
          <p>This page builds a history, so that a change can be seen as a change rather than guessed at after the fact.</p>
          <p>What is watched is chosen in Settings → Monitoring. This page shows what the watching found.</p>
          <p><span className="text-zinc-200">Read now</span> measures <span className="text-zinc-200">pools and volumes</span>: pool status, and each volume's capacity and free space, taken from the NAS's API and again from <code>df</code> over SSH so the two can disagree. It never touches a share.</p>
          <p><span className="text-zinc-200">Deep read</span> measures <span className="text-zinc-200">shares</span>, and only shares: it walks each watched one with <code>du</code> and <code>find</code> for its true size and live file count, beside the counts the NAS keeps cached. On a large share this takes minutes and the request stays open throughout.</p>
          <p>Because they cover different things, the two reads return different numbers of readings and neither replaces the other.</p>
          <p>Every measurement carries the moment it was taken, so one kind of read never overwrites the other. Anything marked <span className="text-zinc-200">cached</span> or <span className="text-zinc-200">rounded</span> is a figure that lost accuracy before NASQuay saw it.</p>
        </Help>
        {units.map((one) => (
          <button
            key={one.id}
            onClick={() => setSelected(one.id)}
            className={
              one.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-700 text-zinc-200 hover:border-zinc-500"
            }
          >
            {one.name}
          </button>
        ))}

      </div>

      {nas && (
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className={running === "fast" ? "btn-active" : "btn"}
            onClick={() => collect("fast")}
            disabled={!!busy}
          >
            Read now
          </button>
          <button
            className={running === "slow" ? "btn-active" : "btn"}
            onClick={() => collect("slow")}
            disabled={!!busy}
          >
            Deep read
          </button>
        </div>
      )}

      {(error || note) && (
        <div className={error ? "text-sm text-red-400" : "text-sm text-zinc-300"}>
          {error || note}
        </div>
      )}


      {!busy && raised.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-xs uppercase tracking-wide text-zinc-300">Flags</h2>
          {raised.map((flag) => (
            <div
              key={flag.id}
              className={
                "card space-y-1 border-l-2 " +
                (flag.severity === "error" ? "border-l-red-500" : "border-l-amber-500")
              }
            >
              <div className="flex items-center gap-3 flex-wrap">
                <span
                  className={
                    flag.severity === "error" ? "text-sm text-red-400" : "text-sm text-amber-400"
                  }
                >
                  {flag.rule}
                </span>
                <span className="text-xs text-zinc-300">{when(flag.raised_at)}</span>
                {flag.acknowledged_by && (
                  <span className="text-xs text-zinc-400">seen by {flag.acknowledged_by}</span>
                )}
                <span className="flex gap-2 ml-auto">
                  {!flag.acknowledged_at && (
                    <button className="btn" onClick={() => settle(flag, false)}>
                      Acknowledge
                    </button>
                  )}
                  <button className="btn" onClick={() => settle(flag, true)}>
                    Clear
                  </button>
                </span>
              </div>
              <div className="text-xs text-zinc-200">{flag.detail}</div>
            </div>
          ))}
          <div className="text-xs text-zinc-400">
            Clearing a flag by hand does not stop the rule — if the condition still holds, the
            next read raises it again.
          </div>
        </div>
      )}

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {busy && <Busy label={busy} />}

      {!busy && nas && mine.length === 0 && (
        <div className="card text-sm text-zinc-300">
          Nothing is watched on {nas.name} yet. Choose what to watch in Settings → Monitoring.
        </div>
      )}

      {!busy &&
        GROUPS.map(({ kind, title, filled }) => {
          const group = watching.filter((target) => target.kind === kind);
          if (group.length === 0) return null;
          return (
            <div key={kind} className="space-y-2">
              <h2 className="text-xs uppercase tracking-wide text-zinc-300">
                {title}
                <span className="normal-case tracking-normal text-zinc-400">
                  {" "}— filled by {filled}
                </span>
              </h2>
              {group.map((target) => {
                const seen = latest.get(target.id) ?? [];
                return (
                  <div key={target.id} className="card space-y-2">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="h-2 w-2 bg-emerald-400 shrink-0" />
                      <span className="text-sm">{target.ref}</span>
                      {target.label && (
                        <span className="text-xs text-zinc-300">{target.label}</span>
                      )}
                      <span className="text-xs text-zinc-300 ml-auto">
                        {target.last_reading_at
                          ? `last read ${when(target.last_reading_at)}`
                          : "never read"}
                      </span>
                    </div>

                    {kind === "volume" && seen.length > 0 &&
                      !seen.some((one) => one.metric.startsWith("df_")) && (
                        <div className="text-xs text-amber-400">
                          No df reading — this volume has no watched share for df to measure
                          through, so its free space has only one source and cannot be
                          cross-checked.
                        </div>
                      )}

                    {seen.length > 0 && (
                      <div className="grid md:grid-cols-2 gap-x-12">
                        {seen.map((reading) => {
                          const key = `${target.id}:${reading.metric}`;
                          const open = history?.key === key;
                          return (
                            <button
                              key={reading.metric}
                              onClick={() => openHistory(target, reading.metric)}
                              title="Show this metric's history"
                              className={
                                "flex items-center gap-2 text-xs py-0.5 border-b text-left w-full " +
                                (open
                                  ? "border-amber-500/40 text-amber-400"
                                  : "border-zinc-800/40 hover:border-zinc-600")
                              }
                            >
                              <span className={open ? "flex-1" : "text-zinc-300 flex-1"}>
                                {reading.metric}
                              </span>
                              <span className={open ? "" : "text-zinc-200"}>{value(reading)}</span>
                              <span className="text-zinc-300">{reading.source}</span>
                              {/* A figure the NAS computed earlier and hands back unchanged. */}
                              {reading.cached && <span className="text-amber-400">cached</span>}
                              {reading.rounded && <span className="text-amber-400">rounded</span>}
                              <span className="text-zinc-400">
                                {when(reading.taken_at).slice(5, 16)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {history && history.key.startsWith(`${target.id}:`) && (
                      <div className="border-t border-zinc-800 pt-3 space-y-2">
                        <div className="text-xs text-zinc-200">
                          {history.key.split(":")[1]} on {target.ref}
                        </div>
                        {historyBusy ? (
                          <div className="text-xs text-zinc-300">Reading the history…</div>
                        ) : (
                          <Series
                            readings={history.readings}
                            format={(figure) =>
                              history.key.endsWith("_bytes")
                                ? bytes(figure)
                                : figure.toLocaleString()
                            }
                          />
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}

      {/* Kept visible rather than hidden: knowing what is not being watched is part of
          knowing what the readings above do and do not cover. */}
      {!busy && ignored.length > 0 && (
        <div className="space-y-2 pt-4">
          <h2 className="text-xs uppercase tracking-wide text-zinc-300">Unmonitored</h2>
          <div className="card">
            <div className="text-xs text-zinc-300 pb-2">
              Nothing is read from these. Switch them on in Settings → Monitoring.
            </div>
            <div className="grid md:grid-cols-3 gap-x-8">
              {ignored.map((target) => (
                <div
                  key={target.id}
                  className="flex items-center gap-2 text-xs py-1 border-b border-zinc-800/40"
                >
                  <span className="h-2 w-2 bg-zinc-700 shrink-0" />
                  <span className="text-zinc-300">{target.ref}</span>
                  <span className="text-zinc-300 ml-auto">{target.kind}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
