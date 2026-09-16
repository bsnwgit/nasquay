import { useEffect, useState } from "react";
import { api, type Flag, type Nas, type Reading, type Run, type Target } from "../api";
import Busy from "../components/Busy";
import Trouble, { troubled } from "../components/Trouble";
import Help from "../components/Help";
import { bytes, when } from "../utils/format";

// One screen that answers "is anything wrong". Everything here is already recorded — this
// page adds no new reading and contacts no NAS. It is a view, so it is cheap to open and
// safe to leave on a wall.

const usage = (used?: number, capacity?: number) =>
  used && capacity ? Math.min(100, Math.round((used / capacity) * 100)) : null;

export default function Dashboard() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [readings, setReadings] = useState<Reading[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState("Loading");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.allSettled([
      api.nas.list(),
      api.monitoring.targets(),
      api.monitoring.readings({ limit: 1500 }),
      api.monitoring.flags(),
      api.monitoring.runs(20),
    ])
      .then(([nasList, found, taken, open, recent]) => {
        if (nasList.status === "fulfilled") setUnits(nasList.value);
        if (found.status === "fulfilled") setTargets(found.value);
        else setError(found.reason instanceof Error ? found.reason.message : "Could not load");
        if (taken.status === "fulfilled") setReadings(taken.value);
        if (open.status === "fulfilled") setFlags(open.value);
        if (recent.status === "fulfilled") setRuns(recent.value);
      })
      .finally(() => setBusy(""));
  }, []);

  // The most recent value of one metric on one target.
  const latest = new Map<string, Reading>();
  for (const reading of readings) {
    const key = `${reading.target_id}:${reading.metric}`;
    if (!latest.has(key)) latest.set(key, reading);
  }
  const valueOf = (targetId: number, metric: string) =>
    latest.get(`${targetId}:${metric}`)?.value ?? undefined;

  const volumes = targets.filter((one) => one.kind === "volume" && one.enabled);
  const mounts = targets.filter((one) => one.kind === "client_mount" && one.enabled);
  const errors = flags.filter((one) => one.severity === "error");
  const warnings = flags.filter((one) => one.severity !== "error");
  // Collection failing is itself a problem, and a bigger one than most flags: it means the
  // rest of this page may be describing a state that no longer holds.
  const broken = troubled(runs).filter((one) => one.status === "failed").length;
  const partial = troubled(runs).filter((one) => one.status === "partial").length;
  const wrong = errors.length + broken;
  const iffy = warnings.length + partial;
  const newestReading = readings.reduce(
    (newest, one) => (one.taken_at > newest ? one.taken_at : newest),
    "",
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Dashboard</h1>
        <Help>
          <p>Whether anything is wrong, on one screen. Every figure here was already recorded — this page reads the database and contacts no NAS, so opening it costs nothing and wakes nothing up.</p>
          <p>A volume's bar is its own capacity. The age of the newest reading is shown because a dashboard of stale figures that looks calm is worse than no dashboard.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {newestReading && (
          <span className="text-xs text-zinc-400 ml-auto">
            newest reading {when(newestReading)}
          </span>
        )}
      </div>

      <Trouble runs={runs} />

      {busy && <Busy label={busy} />}

      {!busy && (
        <>
          <div
            className={
              "card flex items-center gap-4 border-l-2 " +
              (wrong ? "border-l-red-500" : iffy ? "border-l-amber-500" : "border-l-emerald-500")
            }
          >
            <span
              className={
                wrong
                  ? "text-2xl text-red-400"
                  : iffy
                    ? "text-2xl text-amber-400"
                    : "text-2xl text-emerald-400"
              }
            >
              {wrong || iffy || "OK"}
            </span>
            <span className="text-sm text-zinc-200">
              {[
                errors.length && `${errors.length} flagged`,
                broken && `collection failing`,
                partial && !broken && `collection only partly working`,
                warnings.length && `${warnings.length} to look at`,
              ]
                .filter(Boolean)
                .join(" · ") || "Nothing is flagged, and collection is working"}
            </span>
            <span className="text-xs text-zinc-400 ml-auto">
              {units.filter((one) => one.enabled).length} NAS · {volumes.length} volumes ·{" "}
              {mounts.length} mounts watched
            </span>
          </div>

          {flags.length > 0 && (
            <div className="space-y-2">
              {flags.map((flag) => (
                <div
                  key={flag.id}
                  className={
                    "card border-l-2 " +
                    (flag.severity === "error" ? "border-l-red-500" : "border-l-amber-500")
                  }
                >
                  <div className="flex items-center gap-3 flex-wrap">
                    <span
                      className={
                        flag.severity === "error"
                          ? "text-sm text-red-400"
                          : "text-sm text-amber-400"
                      }
                    >
                      {flag.rule}
                    </span>
                    <span className="text-xs text-zinc-400">{when(flag.raised_at)}</span>
                    {flag.acknowledged_by && (
                      <span className="text-xs text-zinc-400">
                        seen by {flag.acknowledged_by}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-zinc-200">{flag.detail}</div>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Volumes</h2>
            <div className="grid md:grid-cols-2 gap-3">
              {volumes.map((volume) => {
                const capacity = valueOf(volume.id, "volume_capacity_bytes");
                const used = valueOf(volume.id, "volume_used_bytes");
                const percent = usage(used, capacity);
                const nas = units.find((one) => one.id === volume.nas_id);
                return (
                  <div key={volume.id} className="card space-y-2">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-sm">{volume.label || `Volume ${volume.ref}`}</span>
                      <span className="text-xs text-zinc-400">{nas?.name}</span>
                      <span className="text-xs text-zinc-300 ml-auto">
                        {percent === null ? "not read" : `${percent}%`}
                      </span>
                    </div>
                    <div className="h-2 w-full bg-zinc-800">
                      <div
                        className={
                          percent !== null && percent >= 90
                            ? "h-2 bg-red-500"
                            : percent !== null && percent >= 75
                              ? "h-2 bg-amber-500"
                              : "h-2 bg-sky-500"
                        }
                        style={{ width: `${percent ?? 0}%` }}
                      />
                    </div>
                    <div className="text-xs text-zinc-400">
                      {bytes(used)} used of {bytes(capacity)}
                    </div>
                  </div>
                );
              })}
              {volumes.length === 0 && (
                <div className="card text-sm text-zinc-300">
                  No volumes are watched. Choose some in Settings → Monitoring.
                </div>
              )}
            </div>
          </div>

          {mounts.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-xs uppercase tracking-wide text-zinc-300">Client mounts</h2>
              <div className="grid md:grid-cols-2 gap-3">
                {mounts.map((one) => {
                  const up = valueOf(one.id, "client_mounted");
                  return (
                    <div key={one.id} className="card flex items-center gap-3">
                      <span
                        className={
                          up === undefined
                            ? "h-2 w-2 bg-zinc-600 shrink-0"
                            : up
                              ? "h-2 w-2 bg-emerald-400 shrink-0"
                              : "h-2 w-2 bg-red-500 shrink-0"
                        }
                      />
                      <span className="text-sm">{one.label || one.ref}</span>
                      <span className="text-xs text-zinc-400 ml-auto">
                        {up === undefined ? "never read" : up ? "mounted" : "not mounted"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
