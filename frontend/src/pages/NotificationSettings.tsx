import { useEffect, useState } from "react";
import { api, type Notifications } from "../api";
import Help from "../components/Help";
import { when } from "../utils/format";

// Where NASQuay sends word when something is flagged.
//
// Two secrets here behave like a NAS token: they go in and never come out. An empty box on
// save means "leave what is stored", so saving the form without retyping a password cannot
// quietly disable the channel it belongs to.

export default function NotificationSettings() {
  const [values, setValues] = useState<Notifications | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [secrets, setSecrets] = useState({ smtp_password: "", ntfy_token: "", slack_webhook: "" });
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.notifications
      .read()
      .then((loaded) => {
        setValues(loaded);
        setDraft({ ...loaded });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load"));

  useEffect(() => {
    load();
  }, []);

  const save = async (extra: Record<string, unknown> = {}) => {
    setError("");
    setNote("");
    try {
      const body: Record<string, unknown> = { ...draft, ...extra };
      if (secrets.smtp_password) body.smtp_password = secrets.smtp_password;
      if (secrets.ntfy_token) body.ntfy_token = secrets.ntfy_token;
      if (secrets.slack_webhook) body.slack_webhook = secrets.slack_webhook;
      delete body.has_smtp_password;
      delete body.has_ntfy_token;
      delete body.has_slack_webhook;
      delete body.last_sent_at;
      delete body.last_result;
      const next = await api.notifications.update(body);
      setValues(next);
      setDraft({ ...next });
      setSecrets({ smtp_password: "", ntfy_token: "", slack_webhook: "" });
      setNote("Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  };

  const test = async () => {
    setError("");
    setNote("Sending…");
    try {
      const result = await api.notifications.test();
      setNote(result.detail);
      if (!result.ok) setError(result.detail);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The test failed");
    }
  };

  const set = (key: string, value: unknown) => setDraft((current) => ({ ...current, [key]: value }));
  const text = (key: string) => String(draft[key] ?? "");
  const on = (key: string) => Boolean(draft[key]);

  // A page that says "Loading…" for ever is telling you nothing. If the read failed, say
  // what failed — a 404 here usually means the service has not been restarted since the
  // endpoint was added.
  if (!values) {
    return error ? (
      <div className="card space-y-1">
        <div className="text-sm text-red-400">Notifications could not be loaded</div>
        <div className="text-xs text-zinc-200">{error}</div>
      </div>
    ) : (
      <div className="text-sm text-zinc-300">Loading…</div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Notifications</h2>
        <Help>
          <p>Where NASQuay sends word when a rule fires. Both channels are optional and independent — either can be on without the other, and one failing never stops the other.</p>
          <p>A flag is raised once and cleared once, so this is one message per condition, not one every few minutes while it holds. Clearings are sent too: knowing a thing fixed itself is as useful as knowing it broke.</p>
          <p>Warnings are off by default. A divergence of a few percent is worth seeing on a page, not at three in the morning.</p>
          <p>The password and token go in but never come out. Leaving them blank keeps what is stored.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      <div className="card space-y-3">
        <div className="text-sm">What is worth sending</div>
        <div className="flex gap-2 flex-wrap">
          {[
            { key: "on_error", label: "errors" },
            { key: "on_warning", label: "warnings" },
            { key: "on_cleared", label: "when a flag clears" },
          ].map((one) => (
            <button
              key={one.key}
              className={on(one.key) ? "btn-on" : "btn-off"}
              onClick={() => save({ [one.key]: !on(one.key) })}
            >
              {one.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card space-y-3">
        <div className="flex items-center gap-3">
          <button
            className={on("email_enabled") ? "btn-on" : "btn-off"}
            onClick={() => save({ email_enabled: !on("email_enabled") })}
          >
            {on("email_enabled") ? "email on" : "email off"}
          </button>
          <span className="text-xs text-zinc-300">a record that arrives and stays</span>
        </div>
        <div className="grid md:grid-cols-3 gap-3">
          {[
            { key: "smtp_host", label: "Mail server" },
            { key: "smtp_port", label: "Port", number: true },
            { key: "smtp_user", label: "Username" },
            { key: "mail_from", label: "From" },
            { key: "mail_to", label: "To (comma separated)" },
          ].map((one) => (
            <label key={one.key} className="space-y-1">
              <span className="text-xs text-zinc-300">{one.label}</span>
              <input
                className="field"
                type={one.number ? "number" : "text"}
                value={text(one.key)}
                onChange={(e) => set(one.key, one.number ? Number(e.target.value) : e.target.value)}
              />
            </label>
          ))}
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Security</span>
            <select
              className="field"
              value={text("smtp_security")}
              onChange={(e) => set("smtp_security", e.target.value)}
            >
              <option value="starttls">STARTTLS</option>
              <option value="tls">TLS</option>
              <option value="none">none</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">
              Password {values.has_smtp_password && <span className="text-zinc-300">(set)</span>}
            </span>
            <input
              className="field"
              type="password"
              placeholder={values.has_smtp_password ? "leave blank to keep" : ""}
              value={secrets.smtp_password}
              onChange={(e) => setSecrets({ ...secrets, smtp_password: e.target.value })}
            />
          </label>
        </div>
      </div>

      <div className="card space-y-3">
        <div className="flex items-center gap-3">
          <button
            className={on("ntfy_enabled") ? "btn-on" : "btn-off"}
            onClick={() => save({ ntfy_enabled: !on("ntfy_enabled") })}
          >
            {on("ntfy_enabled") ? "push on" : "push off"}
          </button>
          <span className="text-xs text-zinc-300">ntfy, which reaches a phone</span>
        </div>
        <div className="grid md:grid-cols-3 gap-3">
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Server</span>
            <input
              className="field"
              value={text("ntfy_server")}
              onChange={(e) => set("ntfy_server", e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Topic</span>
            <input
              className="field"
              value={text("ntfy_topic")}
              onChange={(e) => set("ntfy_topic", e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">
              Token {values.has_ntfy_token && <span className="text-zinc-300">(set)</span>}
            </span>
            <input
              className="field"
              type="password"
              placeholder={values.has_ntfy_token ? "leave blank to keep" : "only if the topic needs one"}
              value={secrets.ntfy_token}
              onChange={(e) => setSecrets({ ...secrets, ntfy_token: e.target.value })}
            />
          </label>
        </div>
      </div>

      <div className="card space-y-3">
        <div className="flex items-center gap-3">
          <button
            className={on("slack_enabled") ? "btn-on" : "btn-off"}
            onClick={() => save({ slack_enabled: !on("slack_enabled") })}
          >
            {on("slack_enabled") ? "Slack on" : "Slack off"}
          </button>
          <span className="text-xs text-zinc-300">where people are already looking</span>
        </div>
        <label className="space-y-1 block">
          <span className="text-xs text-zinc-300">
            Incoming webhook URL{" "}
            {values.has_slack_webhook && <span className="text-zinc-300">(set)</span>}
          </span>
          <input
            className="field"
            type="password"
            placeholder={
              values.has_slack_webhook
                ? "leave blank to keep"
                : "https://hooks.slack.com/services/..."
            }
            value={secrets.slack_webhook}
            onChange={(e) => setSecrets({ ...secrets, slack_webhook: e.target.value })}
          />
          <span className="block text-xs text-zinc-300">
            The webhook decides the channel, and anyone holding it can post there — so it is
            treated as a credential: encrypted, and never shown again.
          </span>
        </label>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <button className="btn-primary" onClick={() => save()}>
          Save
        </button>
        <button className="btn" onClick={test}>
          Send a test
        </button>
        {values.last_sent_at && (
          <span className="text-xs text-zinc-300">
            last sent {when(values.last_sent_at)} — {values.last_result}
          </span>
        )}
      </div>
    </div>
  );
}
