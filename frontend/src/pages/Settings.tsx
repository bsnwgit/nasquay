import { useEffect, useState } from "react";
import { api, type Network } from "../api";
import Users from "./Users";
import Roles from "./Roles";
import NasSettings from "./NasSettings";
import MonitoringSettings from "./MonitoringSettings";
import KeysSettings from "./KeysSettings";
import CertSettings from "./CertSettings";
import NotificationSettings from "./NotificationSettings";
import AiSettings from "./AiSettings";
import RoutineSettings from "./RoutineSettings";
import Reports from "./Reports";
import Help from "../components/Help";
import Confirm from "../components/Confirm";

// One settings section with tabs down the side, the way the suite's other apps do it.
// Tools are not a tab: they belong to a NAS, so they live inside its row.
// The host's own zones, so the list matches what the server will accept. A browser
// without Intl.supportedValuesOf falls back to a short list plus whatever is already set.
const ZONES: string[] = (() => {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    const all = intl.supportedValuesOf?.("timeZone");
    if (all?.length) return all;
  } catch {
    // fall through
  }
  return ["UTC", "America/New_York", "America/Chicago", "America/Denver",
          "America/Los_Angeles", "Europe/London", "Europe/Paris", "Australia/Sydney"];
})();

const TABS = ["General", "NAS", "Monitoring", "Notifications", "Routines", "Reports", "AI", "Certificates", "SSH keys", "Users", "Roles", "Network"] as const;
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
                : "w-full text-left px-2 py-1 text-sm border border-transparent text-zinc-200 hover:border-zinc-600"
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
        {tab === "Notifications" && <NotificationSettings />}
        {tab === "Routines" && <RoutineSettings />}
        {tab === "Reports" && <Reports manage />}
        {tab === "AI" && <AiSettings />}
        {tab === "Certificates" && <CertSettings />}
        {tab === "SSH keys" && <KeysSettings />}
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
  const [confirming, setConfirming] = useState(false);

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
    setConfirming(false);
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
      <Heading
        title="General"
        note={note}
        error={error}
        help={
          <>
            <p>Settings that apply to NASQuay itself rather than to any NAS.</p>
            <p><span className="text-zinc-200">Dashboard access</span> decides whether the dashboard needs a sign-in. The settings pages always do, whatever this says.</p>
            <p><span className="text-zinc-200">Time zone</span> applies everywhere. Times NASQuay recorded are stored in UTC and shown in this zone; times a NAS reported are that NAS's own clock and are shown exactly as given, because converting them would claim an offset the NAS never stated.</p>
            <p><span className="text-zinc-200">Audit retention</span> is how long the record of every action is kept.</p>
          </>
        }
      />

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
          <span className="text-xs uppercase tracking-wide text-zinc-300">Time zone</span>
          <select
            className="field"
            value={String(values.timezone ?? "UTC")}
            onChange={(e) => save({ timezone: e.target.value })}
          >
            {ZONES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <span className="block text-xs text-zinc-300">
            Every time NASQuay records is stored in UTC and shown in this zone. Times a NAS
            reported are that NAS's own clock and are shown exactly as it gave them.
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
            key={String(values.audit_retention_days ?? "")}
            defaultValue={Number(values.audit_retention_days ?? 365)}
            onBlur={(e) => save({ audit_retention_days: Number(e.target.value) })}
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Delivered reports carry
          </span>
          <select
            className="field"
            value={String(values.report_delivery ?? "both")}
            onChange={(e) => save({ report_delivery: e.target.value })}
          >
            <option value="attachment">the document</option>
            <option value="link">a link back to NASQuay</option>
            <option value="both">both</option>
          </select>
          <span className="block text-xs text-zinc-300">
            Only email can carry an attachment; a push always sends the text.
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Address NASQuay is reached at
          </span>
          <input
            className="field font-mono text-xs"
            placeholder="https://nasquay.example.com"
            key={String(values.report_link_base ?? "")}
            defaultValue={String(values.report_link_base ?? "")}
            onBlur={(e) => save({ report_link_base: e.target.value })}
          />
          <span className="block text-xs text-zinc-300">
            For the links in a delivered report. NASQuay cannot know this itself — it sees
            whatever address a proxy hands it.
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Report retention (days)
          </span>
          <input
            className="field"
            type="number"
            min={7}
            max={3650}
            key={String(values.report_retention_days ?? "")}
            defaultValue={Number(values.report_retention_days ?? 365)}
            onBlur={(e) => save({ report_retention_days: Number(e.target.value) })}
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Folders hidden everywhere
          </span>
          <input
            className="field font-mono text-xs"
            key={String(values.files_hidden_names ?? "")}
            defaultValue={(values.files_hidden_names as string[] | undefined)?.join(", ") ?? ""}
            onBlur={(e) =>
              save({
                files_hidden_names: e.target.value
                  .split(",")
                  .map((name) => name.trim())
                  .filter(Boolean),
              })
            }
          />
          <span className="block text-xs text-zinc-300">
            Folder names left out of the file listings wherever they appear, on every NAS —
            QTS's housekeeping directories by default. Names, separated by commas, not paths.
            Presentation only: hiding a folder grants and withholds nothing. One share, or one
            folder in one place, is hidden per NAS under Settings → NAS instead.
          </span>
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
        <button className="btn-danger" onClick={() => setConfirming(true)}>
          Restart NASQuay
        </button>

        {confirming && (
          <Confirm
            title="Restart NASQuay now?"
            danger="Everyone using it is disconnected, and anything running — a collection, a routine, a report — is stopped where it is."
            detail={
              network?.restart_required
                ? `It will come back on ${network.host}:${network.port}, which is not the address you are using now.`
                : "It comes back in a few seconds. Reload the page then."
            }
            confirmLabel="Restart NASQuay"
            busyLabel="Restarting…"
            onConfirm={restart}
            onCancel={() => setConfirming(false)}
          />
        )}
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
      <Heading
        title="Network"
        note={note}
        error={error}
        help={
          <>
            <p>Where NASQuay listens. The address is chosen from what this host actually has rather than typed, so it cannot be set to something that does not exist.</p>
            <p><span className="text-zinc-200">127.0.0.1</span> means only this machine can reach it, which is right when a reverse proxy sits in front and terminates TLS. <span className="text-zinc-200">0.0.0.0</span> means every interface.</p>
            <p>A change here takes effect on the next restart, and if the new address is wrong you will need the host's own console to put it back.</p>
          </>
        }
      />

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

function Heading({
  title,
  note,
  error,
  help,
}: {
  title: string;
  note: string;
  error: string;
  help?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <h1 className="text-sm uppercase tracking-wide text-zinc-300">{title}</h1>
      {help && <Help>{help}</Help>}
      {note && <span className="text-sm text-amber-400">{note}</span>}
      {error && <span className="text-sm text-red-400">{error}</span>}
    </div>
  );
}
