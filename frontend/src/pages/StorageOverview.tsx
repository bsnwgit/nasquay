import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import Help from "../components/Help";
import { bytes } from "../utils/format";

// Every NAS's storage on one screen. Unlike the Storage page, which examines one box in
// detail, this asks each of them the same question at once and puts the answers side by
// side — because "which volume is closest to full" is a question about all of them.

type Volume = {
  vol_no?: string;
  vol_label?: string;
  capacity_bytes?: number;
  freesize_bytes?: number;
  used_percent?: number;
};

type Raid = { raid_status?: string; disk_model?: string; disk_capacity?: string };

type Pool = {
  pool_id?: string;
  pool_status?: string;
  pool_capacity?: number;
  pool_freesize?: number;
  raid_info?: Raid[];
  volumes?: Volume[];
};

type Answer = { nas: Nas; pools: Pool[]; error?: string };

// QTS reports a healthy pool as "0"; anything else is the NAS saying something is wrong
// without saying what, so it is shown as given rather than translated.
const healthy = (status?: string) => status === "0" || status === undefined;

export default function StorageOverview() {
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [busy, setBusy] = useState("Reading every NAS");
  const [error, setError] = useState("");

  useEffect(() => {
    api.nas
      .list()
      .then(async (list) => {
        const enabled = list.filter((one) => one.enabled);
        const results = await Promise.allSettled(
          enabled.map((one) => api.run(one.id, "list_storages")),
        );
        setAnswers(
          enabled.map((nas, index) => {
            const result = results[index];
            if (result.status === "fulfilled") {
              const data = (result.value.json_result ?? {}) as { pools?: Pool[] };
              return { nas, pools: data.pools ?? [] };
            }
            return {
              nas,
              pools: [],
              error:
                result.reason instanceof Error ? result.reason.message : "could not be read",
            };
          }),
        );
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"))
      .finally(() => setBusy(""));
  }, []);

  const volumes = answers.flatMap((answer) =>
    (answer.pools ?? []).flatMap((pool) =>
      (pool.volumes ?? []).map((volume) => ({ nas: answer.nas.name, pool, volume })),
    ),
  );
  const fullest = [...volumes].sort(
    (a, b) => (b.volume.used_percent ?? 0) - (a.volume.used_percent ?? 0),
  );
  const unwell = answers.flatMap((answer) =>
    (answer.pools ?? [])
      .filter((pool) => !healthy(pool.pool_status))
      .map((pool) => ({ nas: answer.nas.name, pool })),
  );
  const capacity = volumes.reduce((sum, one) => sum + (one.volume.capacity_bytes ?? 0), 0);
  const free = volumes.reduce((sum, one) => sum + (one.volume.freesize_bytes ?? 0), 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Storage overview</h1>
        <Help>
          <p>Every NAS's pools and volumes at once, read live rather than from history — this is the current state, not a trend.</p>
          <p>Volumes are ordered by how full they are, so the one about to become a problem is at the top rather than wherever it happens to sit on its own box.</p>
          <p>A pool the NAS does not report as healthy is raised above everything else. QTS gives a bare status code with no explanation, so it is shown exactly as given rather than translated into a guess.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {busy && <Busy label={busy} />}

      {!busy && (
        <>
          <div className="card flex items-center gap-4 flex-wrap">
            <span className="text-sm text-zinc-200">
              {bytes(capacity - free)} used of {bytes(capacity)}
            </span>
            <span className="text-xs text-zinc-300">
              {bytes(free)} free across {volumes.length}{" "}
              {volumes.length === 1 ? "volume" : "volumes"} on {answers.length}{" "}
              {answers.length === 1 ? "NAS" : "NAS units"}
            </span>
          </div>

          {unwell.map(({ nas, pool }) => (
            <div key={`${nas}-${pool.pool_id}`} className="card border-l-2 border-l-red-500">
              <div className="text-sm text-red-400">
                {nas}: pool {pool.pool_id} reports status {pool.pool_status}
              </div>
              <div className="text-xs text-zinc-200">
                {(pool.raid_info ?? [])
                  .filter((disk) => !disk.disk_model)
                  .map((_, index) => `slot ${index + 1} is unreadable`)
                  .join(", ") || "The NAS did not say which member is at fault."}
              </div>
            </div>
          ))}

          {answers
            .filter((answer) => answer.error)
            .map((answer) => (
              <div key={answer.nas.id} className="card text-sm text-zinc-300">
                {answer.nas.name} {answer.error}
              </div>
            ))}

          <div className="grid md:grid-cols-2 gap-3">
            {fullest.map(({ nas, pool, volume }) => {
              const percent =
                volume.used_percent ??
                (volume.capacity_bytes && volume.freesize_bytes !== undefined
                  ? Math.round(
                      ((volume.capacity_bytes - volume.freesize_bytes) / volume.capacity_bytes) *
                        100,
                    )
                  : 0);
              return (
                <div key={`${nas}-${volume.vol_no}`} className="card space-y-2">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-sm">{volume.vol_label || `Volume ${volume.vol_no}`}</span>
                    <span className="text-xs text-zinc-300">
                      {nas} · pool {pool.pool_id}
                    </span>
                    <span className="text-xs text-zinc-200 ml-auto">{percent}%</span>
                  </div>
                  <div className="h-2 w-full bg-zinc-800">
                    <div
                      className={
                        percent >= 90 ? "h-2 bg-red-500" : percent >= 75 ? "h-2 bg-amber-500" : "h-2 bg-sky-500"
                      }
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                  <div className="text-xs text-zinc-300">
                    {bytes(volume.freesize_bytes)} free of {bytes(volume.capacity_bytes)}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
