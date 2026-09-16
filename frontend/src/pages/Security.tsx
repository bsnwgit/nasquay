import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { when } from "../utils/format";

// What the NAS's own security apps report. Most of them are separate QNAP applications that
// may not be installed, and the NAS says so in words — those refusals are shown as they
// arrive rather than as a blank panel, because "Antivirus is not installed" is an answer.
//
// Read-only: starting a scan is a write action in the catalogue and needs a confirmation
// path of its own, which this page does not have.

type Reported = {
  name?: string;
  enabled?: boolean;
  status?: string;
  previous_operation?: string;
  last_reports?: { result?: string; error?: string };
};

type Centre = { apps?: Reported[] };

type Malware = {
  enable?: boolean;
  status?: string;
  last_result?: string;
  last_scan_time_local?: string;
};

const LEVELS = ["basic", "intermediate", "advanced", "custom"] as const;

export default function Security() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [centre, setCentre] = useState<Centre>({});
  const [malware, setMalware] = useState<Malware | null>(null);
  const [malwareError, setMalwareError] = useState("");
  const [level, setLevel] = useState<string | null>(null);
  const [policy, setPolicy] = useState<string>("");
  const [policyBusy, setPolicyBusy] = useState(false);
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
    setBusy(`Reading security on ${nasName}`);
    setError("");
    setLevel(null);
    setPolicy("");

    Promise.allSettled([
      api.run(selected, "get_securitycenter_report"),
      api.run(selected, "malware_scan_report"),
    ])
      .then(([report, scan]) => {
        if (report.status === "fulfilled") {
          setCentre((report.value.json_result ?? {}) as Centre);
        } else {
          setCentre({});
          setError(
            report.reason instanceof Error ? report.reason.message : "Could not read the report",
          );
        }

        if (scan.status === "fulfilled") {
          setMalware((scan.value.json_result ?? {}) as Malware);
          setMalwareError("");
        } else {
          setMalware(null);
          setMalwareError(
            scan.reason instanceof Error ? scan.reason.message : "Not available on this NAS",
          );
        }
      })
      .finally(() => setBusy(""));
  }, [selected, units]);

  const readPolicy = async (which: string) => {
    if (selected === null) return;
    setLevel(which);
    setPolicyBusy(true);
    setPolicy("");
    try {
      const result = await api.run(selected, "get_security_policy_detail", { level: which });
      setPolicy(result.text);
    } catch (err) {
      setPolicy(err instanceof Error ? err.message : "Could not read that policy");
    } finally {
      setPolicyBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-400">Security</h1>
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

      {units.length === 0 && <div className="card text-sm text-zinc-500">No enabled NAS units.</div>}

      {busy && <Busy label={busy} />}

      {!busy && units.length > 0 && (
        <>
          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-500">
              Security applications on {nasName}
            </h2>
            {(centre.apps ?? []).map((app) => (
              <div key={app.name} className="card space-y-1">
                <div className="flex items-center gap-3">
                  <span
                    className={
                      app.enabled ? "h-2 w-2 bg-emerald-400 shrink-0" : "h-2 w-2 bg-zinc-700 shrink-0"
                    }
                  />
                  <span className="text-sm">{app.name}</span>
                  <span className="text-xs text-zinc-500">{app.status}</span>
                  {app.previous_operation && app.previous_operation !== "-" && (
                    <span className="text-xs text-zinc-600 ml-auto">
                      last run {when(app.previous_operation)}
                    </span>
                  )}
                </div>
                <div className="text-xs pl-5">
                  {app.last_reports?.result && (
                    <span className="text-zinc-300">{app.last_reports.result}</span>
                  )}
                  {app.last_reports?.error && (
                    <span className="text-zinc-500">{app.last_reports.error}</span>
                  )}
                </div>
              </div>
            ))}
            {(centre.apps ?? []).length === 0 && !error && (
              <div className="card text-sm text-zinc-500">
                The NAS reported no security applications.
              </div>
            )}
          </div>

          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-500">Malware Remover</h2>
            <div className="card text-xs space-y-1">
              {malware ? (
                <>
                  <div className="text-sm text-zinc-300">{malware.last_result ?? "—"}</div>
                  <div className="text-zinc-500">
                    {malware.status}
                    {malware.last_scan_time_local && ` · ${when(malware.last_scan_time_local)}`}
                    {/* `enable` is the scheduled scan, not whether the app is installed. */}
                    <span className={malware.enable ? "text-zinc-500" : "text-zinc-600"}>
                      {malware.enable ? " · scheduled scanning on" : " · scheduled scanning off"}
                    </span>
                  </div>
                </>
              ) : (
                <div className="text-zinc-500">{malwareError}</div>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-500">Security policy</h2>
            <div className="flex items-center gap-2 flex-wrap">
              {LEVELS.map((one) => (
                <button
                  key={one}
                  onClick={() => readPolicy(one)}
                  className={
                    one === level
                      ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                      : "px-3 py-1 text-sm border border-zinc-700 text-zinc-300 hover:border-zinc-500"
                  }
                >
                  {one}
                </button>
              ))}
            </div>
            {policyBusy && <Busy label={`Reading the ${level} policy on ${nasName}`} />}
            {!policyBusy && policy && (
              <pre className="card text-xs text-zinc-400 whitespace-pre-wrap break-all">
                {policy}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  );
}
