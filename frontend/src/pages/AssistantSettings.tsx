import { useEffect, useState } from "react";
import { api, type ResonanceSettings } from "../api";
import Help from "../components/Help";

// The embedded assistant's settings. The key goes in and never comes out, like a NAS
// token: the API says only whether one is set.

export default function AssistantSettings() {
  const [values, setValues] = useState<ResonanceSettings | null>(null);
  const [key, setKey] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  // The text fields are held here and saved on the button, not on blur: a field that
  // saves when it loses focus saves whatever it holds at that moment, which is empty if
  // anything re-rendered it while it was being typed into.
  const [form, setForm] = useState({ base_url: "", label: "", side: "right", ca_bundle: "" });
  const [dirty, setDirty] = useState(false);

  const load = () =>
    api.resonance
      .settings()
      .then((got) => {
        setValues(got);
        setForm({
          base_url: got.base_url,
          label: got.label,
          side: got.side,
          ca_bundle: got.ca_bundle,
        });
        setDirty(false);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load the assistant settings"),
      );

  useEffect(() => {
    load();
  }, []);

  const save = async (body: Record<string, unknown>, said: string) => {
    setError("");
    setNote("");
    try {
      const got = await api.resonance.save(body);
      setValues(got);
      setNote(said);
      return got;
    } catch (err) {
      setError(err instanceof Error ? err.message : "That could not be saved");
      return null;
    }
  };

  const saveForm = async () => {
    const got = await save(
      {
        base_url: form.base_url.trim(),
        label: form.label.trim() || "Assistant",
        side: form.side,
        ca_bundle: form.ca_bundle,
      },
      "Saved",
    );
    if (got) setDirty(false);
  };

  const change = (field: keyof typeof form, value: string) => {
    setForm((was) => ({ ...was, [field]: value }));
    setDirty(true);
  };

  const test = async () => {
    setError("");
    setNote("");
    try {
      const session = await api.resonance.test();
      const cap = session.cap as Record<string, boolean> | null;
      const granted = cap
        ? Object.entries(cap)
            .filter(([, on]) => on)
            .map(([name]) => name)
            .join(", ")
        : "";
      setNote(
        `The key works. Session lasts ${session.expires_in ?? "?"}s` +
          (granted ? ` · grants ${granted}` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The test failed");
    }
  };

  if (!values) {
    return (
      <div className="card text-sm text-zinc-300">
        {error || "Loading the assistant settings…"}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Assistant (resonance)</h2>
        <Help>
          <p>An assistant panel from a resonance server, embedded in NASQuay's own pages.</p>
          <p>Create an <span className="text-zinc-200">embed key</span> in resonance, for this application, and paste it here with the embed server's address. NASQuay's key never reaches a browser: it asks resonance for a short-lived, single-use code each time the panel opens or renews, and only that code is handed over.</p>
          <p>The address must be the one a <span className="text-zinc-200">browser</span> uses, and its certificate must be trusted by the browser as well as by this host — a frame that does not trust a certificate fails silently, with nothing to click through. NASQuay calls the same address itself, so this host must be able to resolve it too.</p>
          <p>Opening the panel is its own permission, and every code issued is in the audit log under the name it was issued for.</p>
          <p><span className="text-zinc-200">The assistant knows nothing about your NAS units yet.</span> It can talk; it cannot read anything here. What it may read comes later, and each of those reads will pass the same permission check as the pages.</p>
        </Help>
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      <div className="card space-y-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={values.enabled}
            onChange={(e) => save({ enabled: e.target.checked }, e.target.checked ? "Assistant on" : "Assistant off")}
          />
          <span>Show the assistant</span>
          <span className="text-xs text-zinc-300">
            {values.has_key ? "a key is set" : "no key set"} · module {values.module_version}
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">Embed server address</span>
          <input
            className="field"
            placeholder="https://ai.example.com:9701"
            value={form.base_url}
            onChange={(e) => change("base_url", e.target.value)}
          />
          <span className="block text-xs text-zinc-300">
            The embed server, not resonance's admin port — the commonest mistake, and the
            least obvious: the admin port answers a session request with a 404.
          </span>
        </label>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-zinc-300">Launcher label</span>
            <input
              className="field"
              value={form.label}
              onChange={(e) => change("label", e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-zinc-300">Corner</span>
            <select
              className="field"
              value={form.side}
              onChange={(e) => change("side", e.target.value)}
            >
              <option value="right">Bottom right</option>
              <option value="left">Bottom left</option>
            </select>
          </label>
        </div>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">Embed key</span>
          <input
            className="field"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={values.has_key ? "a key is stored — type to replace it" : ""}
          />
          <span className="block text-xs text-zinc-300">
            Stored encrypted and never shown again. Leaving this empty keeps the stored key.
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">
            Certificate authority (optional)
          </span>
          <textarea
            className="field font-mono text-xs h-24"
            placeholder="-----BEGIN CERTIFICATE-----"
            value={form.ca_bundle}
            onChange={(e) => change("ca_bundle", e.target.value)}
          />
          <span className="block text-xs text-zinc-300">
            Only when the embed server's certificate comes from your own authority. This
            is what <span className="text-zinc-200">this host</span> trusts when it calls
            resonance; every browser that opens the panel must trust it too.
          </span>
        </label>

        <div className="flex items-center gap-3 flex-wrap">
          <button className="btn-primary" disabled={!dirty} onClick={saveForm}>
            {dirty ? "Save changes" : "Saved"}
          </button>
          <button
            className="btn"
            disabled={!key}
            onClick={() => save({ embed_key: key }, "Key saved").then(() => setKey(""))}
          >
            Save key
          </button>
          <button className="btn" onClick={test}>
            Test
          </button>
          {values.last_used_at && (
            <span className="text-xs text-zinc-300">
              last used {values.last_used_at} — {values.last_result}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
