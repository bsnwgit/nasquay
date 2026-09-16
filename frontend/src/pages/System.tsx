import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { bytes, duration, when } from "../utils/format";
import Help from "../components/Help";

// What the box itself is doing. Five listings load together, each through /api/run, so a
// role allowed some and refused others still gets the parts it may see.
//
// The NAS reports temperatures with its own warning and error thresholds attached, so
// nothing here hard-codes what counts as hot.

type Temperature = { celsius?: number; warn_temp?: number; error_temp?: number };

type Info = {
  model?: { display_model_name?: string; hostname?: string; serial_number?: string };
  firmware?: { name?: string; version?: string; build?: string; timezone?: string };
  cpu?: {
    usage?: string;
    cores?: number;
    threads?: number;
    temperature?: Temperature;
    detailed_usage?: Record<string, string>;
  };
  memory?: { total_mb?: number; used_mb?: number; free_mb?: number; cache_mb?: number };
  system?: {
    uptime?: number;
    system_temp?: Temperature;
    fans?: { fan_id?: number; speed_rpm?: number; failed?: boolean }[];
  };
  storage?: {
    disks?: { id?: number; installed?: boolean; is_ssd?: boolean; temperature_celsius?: number; temp_alert?: boolean }[];
  };
  network?: {
    interfaces?: {
      name?: string;
      display_name?: string;
      ip_address?: string;
      netmask?: string;
      mac_address?: string;
      max_speed_mbps?: number;
      status?: boolean;
      error_packets?: number;
    }[];
  };
};

type Load = {
  cpu_core_count?: number;
  metrics?: { timestamp?: string; load_1min?: number; load_5min?: number; load_15min?: number }[];
};

type Firmware = {
  firmware?: { name?: string; version?: string; build?: string };
  last_checked_at?: string;
  last_updated_at?: string;
  live_update_status?: string;
  reboot_suggested?: boolean;
  update_locked?: boolean;
};

type Power = {
  schedule_enabled?: boolean;
  entries?: { entry_id?: string; action?: string; day_pattern?: string; hour?: number; minute?: number; enabled?: boolean }[];
};

type Apps = {
  apps?: {
    displayName?: string;
    internalName?: string;
    version?: string;
    type?: string;
    enabled?: boolean;
    installed?: boolean;
    updateAvailable?: boolean;
  }[];
};

// The NAS gives the thresholds; this only decides the colour.
const heat = (reading?: Temperature) => {
  if (!reading?.celsius && reading?.celsius !== 0) return "text-zinc-300";
  if (reading.error_temp && reading.celsius >= reading.error_temp) return "text-red-400";
  if (reading.warn_temp && reading.celsius >= reading.warn_temp) return "text-amber-400";
  return "text-zinc-200";
};

const degrees = (reading?: Temperature) =>
  reading?.celsius || reading?.celsius === 0 ? `${reading.celsius} °C` : "—";

const mb = (value?: number) => (value || value === 0 ? bytes(value * 1024 * 1024) : "—");

export default function System() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [info, setInfo] = useState<Info>({});
  const [load, setLoad] = useState<Load>({});
  const [firmware, setFirmware] = useState<Firmware>({});
  const [power, setPower] = useState<Power>({});
  const [apps, setApps] = useState<Apps>({});
  const [problems, setProblems] = useState<string[]>([]);
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
    setBusy(`Reading ${nasName}`);
    setError("");
    setProblems([]);

    const failures: string[] = [];
    const take = <T,>(
      outcome: PromiseSettledResult<{ json_result: unknown }>,
      what: string,
      apply: (value: T) => void,
    ) => {
      if (outcome.status === "fulfilled") apply((outcome.value.json_result ?? {}) as T);
      else {
        apply({} as T);
        failures.push(
          `${what}: ${outcome.reason instanceof Error ? outcome.reason.message : "refused"}`,
        );
      }
    };

    Promise.allSettled([
      api.run(selected, "get_system_info"),
      api.run(selected, "query_load_avg"),
      api.run(selected, "check_firmware_update"),
      api.run(selected, "list_power_schedule"),
      api.run(selected, "appcenter_list_apps"),
    ])
      .then(([system, loadAvg, update, schedule, appList]) => {
        take<Info>(system, "system", setInfo);
        take<Load>(loadAvg, "load", setLoad);
        take<Firmware>(update, "firmware", setFirmware);
        take<Power>(schedule, "power schedule", setPower);
        take<Apps>(appList, "apps", setApps);
        setProblems(failures);
      })
      .finally(() => setBusy(""));
  }, [selected, units]);

  const latest = load.metrics?.[0];
  const cores = load.cpu_core_count ?? info.cpu?.cores ?? 0;
  const disks = (info.storage?.disks ?? []).filter((disk) => disk.installed);
  const updatable = (apps.apps ?? []).filter((app) => app.updateAvailable);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">System</h1>
        <Help>
          <p>What the box is and what it is doing: model, firmware, uptime, processor and memory load, temperatures, disks, network interfaces, power schedule and installed applications.</p>
          <p>Temperatures are coloured against the thresholds the NAS itself supplies, so nothing here decides what counts as hot.</p>
          <p>Load is shown beside the core count — a load average above the number of cores means work is queuing.</p>
        </Help>
        {units.map((nas) => (
          <button
            key={nas.id}
            onClick={() => setSelected(nas.id)}
            className={
              nas.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-600 text-zinc-200 hover:border-zinc-500"
            }
          >
            {nas.name}
          </button>
        ))}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {problems.length > 0 && !busy && (
        <div className="card text-xs text-zinc-300">Not shown — {problems.join(" · ")}</div>
      )}

      {busy && <Busy label={busy} />}

      {!busy && units.length > 0 && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="card space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">The box</h2>
            <div className="text-sm">
              {info.model?.display_model_name ?? "—"}
              <span className="text-zinc-300"> · {info.model?.hostname}</span>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-300">
              <span>
                {info.firmware?.name} {info.firmware?.version} build {info.firmware?.build}
              </span>
              {info.system?.uptime !== undefined && (
                // The NAS reports uptime in nanoseconds.
                <span>up {duration(Math.floor(info.system.uptime / 1_000_000_000))}</span>
              )}
              {info.model?.serial_number && (
                <span className="text-zinc-300">serial {info.model.serial_number}</span>
              )}
            </div>
            {firmware.reboot_suggested && (
              <div className="text-xs text-amber-400">The NAS is asking to be restarted.</div>
            )}
            <div className="text-xs text-zinc-300">
              Update check {when(firmware.last_checked_at?.replace(/\//g, "-"))} · last updated{" "}
              {when(firmware.last_updated_at?.replace(/\//g, "-"))}
            </div>
          </div>

          <div className="card space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Load</h2>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span>CPU {info.cpu?.usage ?? "—"}</span>
              <span className={heat(info.cpu?.temperature)}>
                CPU {degrees(info.cpu?.temperature)}
              </span>
              <span className={heat(info.system?.system_temp)}>
                system {degrees(info.system?.system_temp)}
              </span>
            </div>
            {latest && (
              <div className="text-xs text-zinc-300">
                load {latest.load_1min} · {latest.load_5min} · {latest.load_15min}
                {cores > 0 && (
                  <span
                    className={
                      (latest.load_1min ?? 0) > cores ? "text-amber-400" : "text-zinc-300"
                    }
                  >
                    {" "}
                    over {cores} cores
                  </span>
                )}
              </div>
            )}
            <div className="text-xs text-zinc-300">
              memory {mb(info.memory?.used_mb)} used, {mb(info.memory?.free_mb)} free of{" "}
              {mb(info.memory?.total_mb)}
              <span className="text-zinc-300"> · {mb(info.memory?.cache_mb)} cache</span>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-300">
              {(info.system?.fans ?? []).map((fan) => (
                <span key={fan.fan_id} className={fan.failed ? "text-red-400" : undefined}>
                  fan {fan.fan_id} {fan.speed_rpm} rpm{fan.failed ? " failed" : ""}
                </span>
              ))}
            </div>
          </div>

          <div className="card space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Disks</h2>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
              {disks.map((disk) => (
                <span
                  key={disk.id}
                  className={disk.temp_alert ? "text-red-400" : "text-zinc-300"}
                >
                  bay {disk.id} {disk.temperature_celsius} °C
                  {disk.is_ssd && <span className="text-zinc-300"> SSD</span>}
                </span>
              ))}
              {disks.length === 0 && <span className="text-zinc-300">No disks reported.</span>}
            </div>

            <h2 className="text-xs uppercase tracking-wide text-zinc-300 pt-2">Power schedule</h2>
            {power.entries?.length ? (
              power.entries.map((entry) => (
                <div key={entry.entry_id} className="text-xs text-zinc-300">
                  {entry.action} {entry.day_pattern} at{" "}
                  {String(entry.hour).padStart(2, "0")}:{String(entry.minute).padStart(2, "0")}
                  <span className={power.schedule_enabled ? "text-zinc-300" : "text-zinc-300"}>
                    {power.schedule_enabled ? " · schedule on" : " · schedule off"}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-xs text-zinc-300">Nothing scheduled.</div>
            )}
          </div>

          <div className="card space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Network</h2>
            {(info.network?.interfaces ?? []).map((nic) => (
              <div key={nic.name} className="flex flex-wrap items-center gap-x-4 text-xs">
                <span className={nic.status ? "text-zinc-200" : "text-zinc-300"}>
                  {nic.name}
                </span>
                <span className="text-zinc-300">{nic.display_name}</span>
                <span className="text-zinc-300">{nic.ip_address || "no address"}</span>
                {nic.max_speed_mbps ? (
                  <span className="text-zinc-300">{nic.max_speed_mbps} Mb/s</span>
                ) : null}
                {!!nic.error_packets && (
                  <span className="text-amber-400">{nic.error_packets} errors</span>
                )}
              </div>
            ))}
          </div>

          <div className="card space-y-2 lg:col-span-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">
              Applications
              {updatable.length > 0 && (
                <span className="text-amber-400"> · {updatable.length} with an update</span>
              )}
            </h2>
            <div className="grid md:grid-cols-2 gap-x-12">
              {(apps.apps ?? []).map((app) => (
                <div
                  key={app.internalName}
                  className="flex items-center gap-2 text-xs py-0.5 border-b border-zinc-600/40"
                >
                  <span className={app.enabled ? "text-zinc-200 flex-1" : "text-zinc-300 flex-1"}>
                    {app.displayName}
                  </span>
                  {!app.enabled && <span className="text-zinc-300">disabled</span>}
                  {app.updateAvailable && <span className="text-amber-400">update</span>}
                  <span className="text-zinc-300">{app.version}</span>
                </div>
              ))}
              {(apps.apps ?? []).length === 0 && (
                <span className="text-xs text-zinc-300">No applications reported.</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
