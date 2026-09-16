import { useEffect, useState } from "react";
import { api, type Nas, type Target } from "../api";
import Busy from "../components/Busy";
import Help from "../components/Help";
import { when } from "../utils/format";

// Choosing what is watched. The Monitoring page shows what the watching found; this decides
// what it looks at in the first place.
//
// Discovery never removes a target: a share that stops being reported is exactly the kind of
// event this app exists to notice, so its history stays and it simply stops gaining readings.

const GROUPS: { kind: string; title: string; note: string }[] = [
  { kind: "pool", title: "Pools", note: "Status, capacity and free space." },
  { kind: "volume", title: "Volumes", note: "Capacity and free space, from the NAS and from df." },
  { kind: "share", title: "Shares", note: "True size and live file count on a deep read." },
  { kind: "client_mount", title: "Client mounts", note: "A client's own view of a mount." },
];

export default function MonitoringSettings() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.monitoring
      .targets()
      .then(setTargets)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load targets"));

  useEffect(() => {
    setBusy("Loading");
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

  const discover = async () => {
    if (!nas) return;
    setBusy(`Asking ${nas.name} what there is to watch`);
    setError("");
    setNote("");
    try {
      const result = await api.monitoring.discover(nas.id);
      setNote(
        `${result.found} found, ${result.added} new` +
          (result.problems.length ? ` — ${result.problems.join(" · ")}` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed");
    } finally {
      setBusy("");
    }
  };

  const importHistory = async () => {
    if (!nas) return;
    setBusy(`Importing ${nas.name}'s own usage history`);
    setError("");
    setNote("");
    try {
      const result = await api.monitoring.backfill(nas.id);
      const windows = Object.entries(result.windows)
        .map(([label, count]) => `${count} from the ${label}`)
        .join(", ");
      setNote(
        `${result.readings} historical readings — ${windows}` +
          (result.problems.length ? ` · ${result.problems.join(" · ")}` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy("");
    }
  };

  const toggle = async (target: Target) => {
    try {
      await api.monitoring.setTarget(target.id, !target.enabled);
      setTargets((current) =>
        current.map((one) => (one.id === target.id ? { ...one, enabled: !one.enabled } : one)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change that target");
    }
  };

  const setAll = async (kind: string, enabled: boolean) => {
    const group = mine.filter((target) => target.kind === kind && target.enabled !== enabled);
    for (const target of group) {
      try {
        await api.monitoring.setTarget(target.id, enabled);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not change that target");
        break;
      }
    }
    await load();
  };

  const mine = targets.filter((target) => target.nas_id === selected);
  const watched = mine.filter((target) => target.enabled).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">What is watched</h2>
        <Help>
          <p>Discovery asks a NAS what exists and makes a target of each pool, volume and share. It reads nothing about their contents — that is what the Monitoring page's reads do.</p>
          <p>Switching a target off stops it gaining readings but keeps everything already recorded.</p>
          <p><span className="text-zinc-200">Import history</span> pulls the NAS's own usage figures for every watched volume and pool — about a year of them — so there is a baseline before NASQuay was installed. Those readings are marked rounded, because QNAP gives only three or four significant digits and mislabels the units, which NASQuay converts back. Running it again replaces the import rather than doubling it.</p>
          <p>Nothing is ever removed by discovery. A share that disappears from the NAS keeps its target and its history, because a share disappearing is precisely what this is here to catch.</p>
        </Help>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
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
        <div className="flex items-center gap-3 flex-wrap">
          <button className="btn" onClick={discover} disabled={!!busy}>
            Discover on {nas.name}
          </button>
          <button className="btn" onClick={importHistory} disabled={!!busy}>
            Import history
          </button>
          <span className="text-xs text-zinc-300">
            {watched} of {mine.length} watched
          </span>
          {error && <span className="text-sm text-red-400">{error}</span>}
          {note && !error && <span className="text-sm text-zinc-300">{note}</span>}
        </div>
      )}

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {busy && <Busy label={busy} />}

      {!busy && nas && mine.length === 0 && (
        <div className="card text-sm text-zinc-300">
          Nothing is known about {nas.name} yet. Press Discover.
        </div>
      )}

      {!busy &&
        GROUPS.map(({ kind, title, note: what }) => {
          const group = mine.filter((target) => target.kind === kind);
          if (group.length === 0) return null;
          return (
            <div key={kind} className="card space-y-2">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-sm">{title}</span>
                <span className="text-xs text-zinc-300">{what}</span>
                <span className="flex gap-2 ml-auto">
                  <button className="btn" onClick={() => setAll(kind, true)}>
                    All
                  </button>
                  <button className="btn" onClick={() => setAll(kind, false)}>
                    None
                  </button>
                </span>
              </div>
              <div className="grid md:grid-cols-2 gap-x-8">
                {group.map((target) => (
                  <div
                    key={target.id}
                    className="flex items-center gap-3 text-xs py-1 border-b border-zinc-800/40"
                  >
                    <button
                      className={target.enabled ? "btn-on" : "btn-off"}
                      onClick={() => toggle(target)}
                    >
                      {target.enabled ? "watched" : "ignored"}
                    </button>
                    <span className="text-zinc-200">{target.ref}</span>
                    {target.label && <span className="text-zinc-300">{target.label}</span>}
                    <span className="text-zinc-300 ml-auto">
                      {target.last_reading_at ? when(target.last_reading_at) : "never read"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
    </div>
  );
}
