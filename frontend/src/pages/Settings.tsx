import { useEffect, useState } from "react";
import { api, type Network } from "../api";
import Users from "./Users";
import Roles from "./Roles";
import NasSettings from "./NasSettings";
import MonitoringSettings from "./MonitoringSettings";
import Help from "../components/Help";

// One settings section with tabs down the side, the way the suite's other apps do it.
// Tools are not a tab: they belong to a NAS, so they live inside its row.
const TABS = ["General", "NAS", "Monitoring", "Users", "Roles", "Network"] as const;
type Tab = (typeof TABS)[number];

export default function Settings() {
  const [tab, setTab] = useState<Tab>("General");

  return (
    <div className="grid gap-4 md:grid-cols-[12rem_1fr]">
      <nav className="card h-fit space-y-1">
        <div className="text-xs uppercase tracking-wide text-zinc-300 pb-1">Settings</div>
        {TABS.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={
              name === tab
                ? "w-full text-left px-2 py-1 text-sm border border-amber-500 text-amber-400"
                : "w-full text-left px-2 py-1 text-sm border border-transparent text-zinc-200 hover:border-zinc-700"
            }
          >
            {name}
          </button>
        ))}
      </nav>

      <div>
        {tab === "General" && <General />}
        {tab === "NAS" && <NasSettings />}
        {tab === "Monitoring" && <MonitoringSettings />}
        {tab === "Users" && <Users />}
        {tab === "Roles" && <Roles />}
        {tab === "Network" && <NetworkSettings />}
      </div>
    </div>
  );
}

function General() {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [network, setNetwork] = useState<Network | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api.settings
      .read()
      .then(setValues)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load settings"));
    // Only to say whether a saved change is waiting for a restart; a role without the
    // system permissions simply sees no note.
    api.system.network().then(setNetwork).catch(() => setNetwork(null));
  }, []);

  const restart = async () => {
    if (!window.confirm("Restart NASQuay now? Everyone using it is disconnected briefly."))
      return;
    setError("");
    setNote("");
    try {
      await api.system.restart();
      setNote(
        network && network.restart_required
          ? `Restarting on ${network.host}:${network.port} — open that address.`
          : "Restarting. Reload in a few seconds.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not restart");
    }
  };

  const save = async (update: Record<string, unknown>) => {
    setError("");
    setNote("");
    try {
      setValues(await api.settings.update(update));
      setNote("Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  };

  return (
    <div className="space-y-4 max-w-xl">
      <Heading title="General" note={note} error={error} />

      <div className="card space-y-4">
        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">Dashboard access</span>
          <select
            className="field"
            value={String(values.dashboard_access ?? "login")}
            onChange={(e) => save({ dashboard_access: e.target.value })}
          >
            <option value="login">Sign-in required</option>
            <option value="open">Open to anyone who can reach the page</option>
          </select>
          <span className="block text-xs text-zinc-300">
            These settings pages always require an admin sign-in.
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Audit log retention (days)
          </span>
          <input
            className="field"
            type="number"
            min={7}
            max={3650}
            defaultValue={Number(values.audit_retention_days ?? 365)}
            onBlur={(e) => save({ audit_retention_days: Number(e.target.value) })}
          />
        </label>
      </div>

      <div className="card space-y-3">
        <div className="text-xs uppercase tracking-wide text-zinc-300">Service</div>
        {network?.restart_required && (
          <div className="text-sm text-amber-400">
            A saved change is waiting: NASQuay will listen on {network.host}:{network.port} after
            the restart.
          </div>
        )}
        <div className="text-xs text-zinc-300">
          NASQuay stops and its service manager starts it again, so settings that are read at
          startup take effect.
        </div>
        <button className="btn" onClick={restart}>
          Restart NASQuay
        </button>
      </div>
    </div>
  );
}

function NetworkSettings() {
  const [network, setNetwork] = useState<Network | null>(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(0);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const load = async () => {
    try {
      const net = await api.system.network();
      setNetwork(net);
      setHost(net.host);
      setPort(net.port);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the network settings");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setError("");
    setNote("");
    try {
      const net = await api.system.setNetwork(host, port);
      setNetwork(net);
      setNote("Saved. Restart to apply it.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the address");
    }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      <Heading title="Network" note={note} error={error} />

      {!network && <div className="card text-sm text-zinc-300">Not available to your role.</div>}

      {network && (
        <div className="card space-y-4">
          <div className="text-xs text-zinc-300">
            Running on {network.running_host}:{network.running_port}
            {network.config_file ? ` · ${network.config_file}` : ""}
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_8rem_auto] md:items-end">
            <label className="block space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-300">Address</span>
              <select className="field" value={host} onChange={(e) => setHost(e.target.value)}>
                {network.choices.map((choice) => (
                  <option key={choice.address} value={choice.address}>
                    {choice.address} — {choice.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-300">Port</span>
              <input
                className="field"
                type="number"
                min={1024}
                max={65535}
                value={port}
                onChange={(e) => setPort(Number(e.target.value))}
              />
            </label>

            <button
              className="btn-primary"
              onClick={save}
              disabled={host === network.host && port === network.port}
            >
              Save
            </button>
          </div>

          <div className="text-xs text-zinc-300">
            Anything other than 127.0.0.1 is reachable from the network over plain HTTP unless a
            TLS reverse proxy sits in front. Ports below 1024 are refused.
          </div>

          {network.restart_required && (
            <div className="text-sm text-amber-400">
              Saved as {network.host}:{network.port}. Restart on the General tab to apply it.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Heading({ title, note, error }: { title: string; note: string; error: string }) {
  return (
    <div className="flex items-center gap-3">
      <h1 className="text-sm uppercase tracking-wide text-zinc-300">{title}</h1>
        <Help>
          <p>NASQuay's own configuration. Everything here is admin-only, and each section is itself a permission.</p>
          <p><span className="text-zinc-200">NAS</span> holds the connections and their credentials. <span className="text-zinc-200">Users</span> and <span className="text-zinc-200">Roles</span> decide who may do what — the roles grid covers every action, including every tool a NAS offers.</p>
          <p>Secrets are written but never read back: the API reports only whether one is set.</p>
        </Help>
      {note && <span className="text-sm text-amber-400">{note}</span>}
      {error && <span className="text-sm text-red-400">{error}</span>}
    </div>
  );
}
