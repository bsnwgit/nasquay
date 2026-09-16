import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import Help from "../components/Help";
import { bytes, duration } from "../utils/format";

// Every NAS's condition on one screen: what it is, how hard it is working, how hot it is,
// and whether anything is asking to be attended to. Read live — this is the current state.

type Temperature = { celsius?: number; warn_temp?: number; error_temp?: number };

type Info = {
  model?: { display_model_name?: string; hostname?: string };
  firmware?: { name?: string; version?: string };
  cpu?: { usage?: string; cores?: number; temperature?: Temperature };
  memory?: { total_mb?: number; used_mb?: number };
  system?: {
    uptime?: number;
    system_temp?: Temperature;
    fans?: { fan_id?: number; speed_rpm?: number; failed?: boolean }[];
  };
  storage?: {
    disks?: { id?: number; installed?: boolean; temperature_celsius?: number; temp_alert?: boolean }[];
  };
};

type Update = { reboot_suggested?: boolean; firmware?: { version?: string } };
type Apps = { apps?: { displayName?: string; updateAvailable?: boolean }[] };

type Answer = { nas: Nas; info: Info; update: Update; apps: Apps; error?: string };

const hot = (reading?: Temperature) =>
  reading?.celsius !== undefined &&
  ((reading.error_temp !== undefined && reading.celsius >= reading.error_temp) ||
    (reading.warn_temp !== undefined && reading.celsius >= reading.warn_temp));

const heat = (reading?: Temperature) => {
  if (reading?.celsius === undefined) return "text-zinc-300";
  if (reading.error_temp !== undefined && reading.celsius >= reading.error_temp) return "text-red-400";
  if (reading.warn_temp !== undefined && reading.celsius >= reading.warn_temp) return "text-amber-400";
  return "text-zinc-200";
};

export default function SystemOverview() {
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [busy, setBusy] = useState("Reading every NAS");
  const [error, setError] = useState("");

  useEffect(() => {
    api.nas
      .list()
      .then(async (list) => {
        const enabled = list.filter((one) => one.enabled);
        const results = await Promise.all(
          enabled.map(async (nas) => {
            const [info, update, apps] = await Promise.allSettled([
              api.run(nas.id, "get_system_info"),
              api.run(nas.id, "check_firmware_update"),
              api.run(nas.id, "appcenter_list_apps"),
            ]);
            return {
              nas,
              info: info.status === "fulfilled" ? ((info.value.json_result ?? {}) as Info) : {},
              update:
                update.status === "fulfilled" ? ((update.value.json_result ?? {}) as Update) : {},
              apps: apps.status === "fulfilled" ? ((apps.value.json_result ?? {}) as Apps) : {},
              error:
                info.status === "rejected"
                  ? info.reason instanceof Error
                    ? info.reason.message
                    : "could not be read"
                  : undefined,
            };
          }),
        );
        setAnswers(results);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"))
      .finally(() => setBusy(""));
  }, []);

  const attention = answers.flatMap((answer) => {
    const notes: string[] = [];
    if (answer.error) notes.push(answer.error);
    if (answer.update.reboot_suggested) notes.push("is asking to be restarted");
    if (hot(answer.info.cpu?.temperature)) notes.push("processor is above its warning threshold");
    if (hot(answer.info.system?.system_temp)) notes.push("chassis is above its warning threshold");
    const failed = (answer.info.system?.fans ?? []).filter((fan) => fan.failed);
    if (failed.length) notes.push(`${failed.length} fan(s) reporting failure`);
    const alerting = (answer.info.storage?.disks ?? []).filter((disk) => disk.temp_alert);
    if (alerting.length) notes.push(`${alerting.length} disk(s) too warm`);
    return notes.map((note) => ({ nas: answer.nas.name, note }));
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">System overview</h1>
        <Help>
          <p>Every NAS's condition at once, read live rather than from history.</p>
          <p>Anything the NAS itself considers out of range is raised to the top. Temperatures are judged against the warning and error thresholds each box supplies, so nothing here decides on its own what counts as too hot.</p>
          <p>Load is shown beside the core count: a load average above the number of cores means work is queuing, not merely that the box is busy.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {busy && <Busy label={busy} />}

      {!busy && (
        <>
          <div
            className={
              "card flex items-center gap-4 border-l-2 " +
              (attention.length ? "border-l-amber-500" : "border-l-emerald-500")
            }
          >
            <span
              className={
                attention.length ? "text-2xl text-amber-400" : "text-2xl text-emerald-400"
              }
            >
              {attention.length || "OK"}
            </span>
            <span className="text-sm text-zinc-200">
              {attention.length
                ? `${attention.length} thing${attention.length === 1 ? "" : "s"} to look at`
                : "Nothing is asking for attention"}
            </span>
          </div>

          {attention.map((one, index) => (
            <div key={`${one.nas}-${index}`} className="card border-l-2 border-l-amber-500">
              <span className="text-sm text-amber-400">{one.nas}</span>{" "}
              <span className="text-xs text-zinc-200">{one.note}</span>
            </div>
          ))}

          <div className="grid md:grid-cols-2 gap-3">
            {answers.map((answer) => {
              const disks = (answer.info.storage?.disks ?? []).filter((disk) => disk.installed);
              const updatable = (answer.apps.apps ?? []).filter((app) => app.updateAvailable);
              return (
                <div key={answer.nas.id} className="card space-y-2">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-sm">{answer.nas.name}</span>
                    <span className="text-xs text-zinc-300">
                      {answer.info.model?.display_model_name}
                    </span>
                    <span className="text-xs text-zinc-300 ml-auto">
                      {answer.info.firmware?.name} {answer.info.firmware?.version}
                    </span>
                  </div>

                  <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
                    <span className="text-zinc-200">CPU {answer.info.cpu?.usage ?? "—"}</span>
                    <span className={heat(answer.info.cpu?.temperature)}>
                      {answer.info.cpu?.temperature?.celsius ?? "—"} °C
                    </span>
                    <span className={heat(answer.info.system?.system_temp)}>
                      chassis {answer.info.system?.system_temp?.celsius ?? "—"} °C
                    </span>
                    {answer.info.system?.uptime !== undefined && (
                      <span className="text-zinc-300">
                        up {duration(Math.floor(answer.info.system.uptime / 1_000_000_000))}
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-zinc-300">
                    memory{" "}
                    {bytes((answer.info.memory?.used_mb ?? 0) * 1024 * 1024)} of{" "}
                    {bytes((answer.info.memory?.total_mb ?? 0) * 1024 * 1024)}
                    <span className="text-zinc-300">
                      {" "}
                      · {disks.length} disks
                      {disks.length > 0 &&
                        `, warmest ${Math.max(
                          ...disks.map((disk) => disk.temperature_celsius ?? 0),
                        )} °C`}
                    </span>
                  </div>

                  {updatable.length > 0 && (
                    <div className="text-xs text-amber-400">
                      {updatable.length} application
                      {updatable.length === 1 ? "" : "s"} with an update:{" "}
                      {updatable.map((app) => app.displayName).join(", ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
