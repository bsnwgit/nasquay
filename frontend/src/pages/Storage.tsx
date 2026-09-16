import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { bytes } from "../utils/format";

// The first page built on /api/run: it calls list_storages on a NAS and lays out what
// comes back. Nothing here talks to a NAS directly, so the role check and the audit
// record happen exactly as they do everywhere else.

type Disk = {
  disk_no?: string;
  pd_alias?: string;
  model_number?: string;
  size?: string;
  type?: string;
  interface?: string;
  vendor_name?: string;
};

type Raid = {
  raid_id?: string;
  raid_level?: string;
  raid_status?: string;
  disks?: Disk[];
};

// QNAP reports pool and RAID state as a number. 0 is healthy; anything else is not, and
// the code alone tells an operator nothing, so each is spelled out.
const POOL_STATUS: Record<string, string> = {
  "0": "healthy",
  "-1": "degraded — the pool is running on fewer disks than it should",
  "-2": "rebuilding",
  "1": "warning",
  "2": "read-only",
};

const statusText = (code?: string) => {
  const key = String(code ?? "");
  return POOL_STATUS[key] ?? `status ${key || "unknown"}`;
};

type Volume = {
  vol_no?: string;
  vol_label?: string;
  capacity_bytes?: number;
  freesize_bytes?: number;
  used_percent?: number;
  thin_volume?: boolean;
};

type Pool = {
  pool_id?: string;
  pool_status?: string;
  pool_capacity?: number;
  pool_freesize?: number;
  raid_info?: Raid[];
  volumes?: Volume[];
};

export default function Storage() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [pools, setPools] = useState<Pool[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

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

  useEffect(() => {
    if (selected === null) return;
    const name = units.find((n) => n.id === selected)?.name ?? "the NAS";
    setBusy(`Reading pools, volumes and disks from ${name}`);
    setError("");
    setPools([]);
    api
      .run(selected, "list_storages")
      .then((result) => {
        const data = (result.json_result ?? {}) as { pools?: Pool[] };
        setPools(data.pools ?? []);
      })
      .catch((err) => {
        setPools([]);
        setError(err instanceof Error ? err.message : "Could not read the storage");
      })
      .finally(() => setBusy(""));
  }, [selected, units]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-400">Storage</h1>
        {units.map((nas) => (
          <button
            key={nas.id}
            onClick={() => setSelected(nas.id)}
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

      {busy && <Busy label={busy} />}

      {units.length === 0 && (
        <div className="card text-sm text-zinc-500">No enabled NAS units.</div>
      )}

      {!busy && !error && units.length > 0 && pools.length === 0 && (
        <div className="card text-sm text-zinc-500">No pools reported.</div>
      )}

      {!busy && pools.map((pool) => {
        const disks = (pool.raid_info ?? []).flatMap((raid) => raid.disks ?? []);
        const degraded = String(pool.pool_status ?? "") !== "0";
        // A disk the NAS lists with no model or size is a slot it cannot read: an empty
        // bay, or a drive that has dropped out. That is usually why a pool is degraded.
        const missing = disks.filter((disk) => !disk.model_number && !disk.size);
        return (
          <div key={pool.pool_id} className="card space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="text-sm">Pool {pool.pool_id}</div>
              <span className={degraded ? "text-xs text-red-400" : "text-xs text-emerald-400"}>
                {statusText(pool.pool_status)}
              </span>
              <span className="text-xs text-zinc-500">
                {bytes(pool.pool_capacity)} capacity · {bytes(pool.pool_freesize)} free
              </span>
              {(pool.raid_info ?? []).map((raid) => (
                <span key={raid.raid_id} className="text-xs text-zinc-500">
                  RAID {raid.raid_level} · {(raid.disks ?? []).length} disks
                </span>
              ))}
            </div>

            {degraded && (
              <div className="border border-red-900 bg-red-950/30 p-3 space-y-2 text-sm">
                <div className="text-red-300">
                  This pool is not healthy — {statusText(pool.pool_status)}.
                </div>

                {(pool.raid_info ?? []).map((raid) => (
                  <div key={raid.raid_id} className="text-xs text-zinc-300">
                    RAID {raid.raid_level}
                    {raid.raid_status ? ` · state ${raid.raid_status}` : ""} ·{" "}
                    {(raid.disks ?? []).length} slots,{" "}
                    {(raid.disks ?? []).filter((d) => d.model_number || d.size).length} readable
                  </div>
                ))}

                {missing.length > 0 && (
                  <div className="text-xs text-red-300">
                    {missing.length} slot{missing.length === 1 ? "" : "s"} the NAS cannot read —{" "}
                    {missing.map((d) => d.pd_alias || d.disk_no || "unknown slot").join(", ")}.
                    Either the bay is empty or the drive has dropped out.
                  </div>
                )}

                <div className="text-xs text-zinc-400">
                  Every readable disk is listed below with its slot and model. A RAID 5 pool
                  with one slot missing still serves data but has no redundancy left: a second
                  failure loses the pool.
                </div>
              </div>
            )}

            {(pool.volumes ?? []).length > 0 && (
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="th">Volume</th>
                    <th className="th">Capacity</th>
                    <th className="th">Free</th>
                    <th className="th">Used</th>
                  </tr>
                </thead>
                <tbody>
                  {(pool.volumes ?? []).map((volume) => {
                    const used = Number(volume.used_percent ?? 0);
                    return (
                      <tr key={volume.vol_no}>
                        <td className="td">
                          {volume.vol_label || `volume ${volume.vol_no}`}
                          {volume.thin_volume && (
                            <span className="text-xs text-zinc-500"> · thin</span>
                          )}
                        </td>
                        <td className="td text-zinc-400">{bytes(volume.capacity_bytes)}</td>
                        <td className="td text-zinc-400">{bytes(volume.freesize_bytes)}</td>
                        <td className="td">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-28 bg-zinc-800">
                              <div
                                className={used >= 90 ? "h-1.5 bg-red-500" : used >= 75 ? "h-1.5 bg-amber-500" : "h-1.5 bg-emerald-600"}
                                style={{ width: `${Math.min(100, Math.max(0, used))}%` }}
                              />
                            </div>
                            <span className="text-xs text-zinc-400">{used}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {disks.length > 0 && (
              <div className="grid md:grid-cols-2 gap-x-12">
                {disks.map((disk, index) => {
                  const unreadable = !disk.model_number && !disk.size;
                  return (
                    <div
                      key={`${disk.disk_no}-${index}`}
                      className="flex items-center gap-2 text-xs py-0.5 border-b border-zinc-800/40 last:border-0"
                    >
                      <span className={unreadable ? "text-red-400 flex-1 truncate" : "text-zinc-300 flex-1 truncate"}>
                        {disk.pd_alias || disk.disk_no || "slot"}
                      </span>
                      <span className={unreadable ? "text-red-400 truncate" : "text-zinc-500 truncate"}>
                        {disk.model_number || "nothing readable in this slot"}
                      </span>
                      <span className="text-zinc-400">{disk.size || "—"}</span>
                      <span className="text-zinc-600">{disk.type || disk.interface || ""}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
