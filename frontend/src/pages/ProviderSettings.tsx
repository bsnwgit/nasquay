import { useEffect, useState } from "react";
import { api, type Certificate, type Provider } from "../api";
import Help from "../components/Help";

// The AI services routines run against. Any number: a small local model and a large
// outside one are good at different work, and each routine names the one it wants.
//
// The API key is write-only, like every secret here: the server says only whether one is
// set, and a blank key field on a save leaves the stored one alone.

type Form = {
  name: string;
  kind: "openai" | "anthropic";
  base_url: string;
  model: string;
  api_key: string;
  timeout_s: number;
  supports_tools: boolean;
  tls_cert_id: number;
};

const BLANK: Form = {
  name: "",
  kind: "openai",
  base_url: "",
  model: "",
  api_key: "",
  timeout_s: 120,
  supports_tools: true,
  tls_cert_id: 0,
};

const PLACEHOLDER = {
  openai: "http://host.example.com:11434/v1",
  anthropic: "https://api.anthropic.com",
};

const fromProvider = (p: Provider): Form => ({
  name: p.name,
  kind: p.kind,
  base_url: p.base_url,
  model: p.model,
  api_key: "",
  timeout_s: p.timeout_s,
  supports_tools: p.supports_tools,
  tls_cert_id: p.tls_cert_id ?? 0,
});

export default function ProviderSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [certs, setCerts] = useState<Certificate[]>([]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.providers
      .list()
      .then(setProviders)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load the providers"),
      );

  useEffect(() => {
    load();
    // Only to offer a choice; a role that cannot list certificates simply sees none.
    api.certificates.list().then(setCerts).catch(() => setCerts([]));
  }, []);

  const act = async (what: () => Promise<unknown>, said: string) => {
    setError("");
    setNote("");
    try {
      await what();
      setNote(said);
      await load();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
      return false;
    }
  };

  const test = async (p: Provider) => {
    setError("");
    setNote("");
    setTesting(p.id);
    try {
      const result = await api.providers.test(p.id);
      if (result.ok) setNote(`${p.name}: ${result.detail}`);
      else setError(`${p.name}: ${result.detail}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The test did not run");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Providers (for routines)</h2>
        <Help>
          <p>The AI services NASQuay's routines can use. Add as many as you like; each routine chooses one.</p>
          <p><span className="text-zinc-200">OpenAI-compatible</span> covers Ollama, LM Studio, vLLM and OpenAI itself. The base URL is the one that ends before <span className="font-mono">/chat/completions</span> — for Ollama that is its address followed by <span className="font-mono">/v1</span>.</p>
          <p><span className="text-zinc-200">Anthropic</span> is the Anthropic Messages API. The base URL is normally <span className="font-mono">https://api.anthropic.com</span>.</p>
          <p>The API key goes in and never comes back out. Leave the field blank when editing to keep the stored key. A local server that needs no key can have one removed.</p>
          <p><span className="text-zinc-200">Tool calling</span> is how a model asks NASQuay to run an action. Small local models often handle it poorly. Test sends a trivial request and, if tool calling is ticked, asks the model to call a harmless probe tool — nothing is run on its behalf. A routine that needs tools is refused a provider that failed that test.</p>
          <p>The timeout is how long to wait for one answer. A small model on modest hardware can need most of a minute when a routine hands it a list of tools.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      <div className="card space-y-3">
        <button
          className="w-full flex items-center gap-3 text-left"
          onClick={() => setAdding((was) => !was)}
        >
          <span className="text-zinc-300 w-3">{adding ? "▾" : "▸"}</span>
          <span className="text-sm">Add provider</span>
          <span className="text-xs text-zinc-300">a local model or an outside service</span>
        </button>
        {adding && (
          <div className="border-t border-zinc-600 pt-3">
            <ProviderForm
              initial={BLANK}
              certs={certs}
              isNew
              hasKey={false}
              onCancel={() => setAdding(false)}
              onSave={async (form) => {
                const { tls_cert_id, ...rest } = form;
                const ok = await act(
                  () => api.providers.create({ ...rest, tls_cert_id: tls_cert_id || null }),
                  `Added ${form.name} — test it next`,
                );
                if (ok) setAdding(false);
              }}
            />
          </div>
        )}
      </div>

      {providers.map((p) => (
        <div key={p.id} className="card space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm">{p.name}</span>
            <span className="text-xs text-zinc-300">
              {p.kind === "openai" ? "OpenAI-compatible" : "Anthropic"} · {p.model}
            </span>
            {!p.enabled && <span className="text-xs text-amber-400">disabled</span>}
            <ToolsBadge provider={p} />
            <span className="flex gap-2 ml-auto">
              <button className="btn" disabled={testing === p.id} onClick={() => test(p)}>
                {testing === p.id ? "Testing…" : "Test"}
              </button>
              <button
                className="btn"
                onClick={() =>
                  act(
                    () => api.providers.update(p.id, { enabled: !p.enabled }),
                    `${p.name} ${p.enabled ? "disabled" : "enabled"}`,
                  )
                }
              >
                {p.enabled ? "Disable" : "Enable"}
              </button>
              <button
                className="btn"
                onClick={() => setEditing((was) => (was === p.id ? null : p.id))}
              >
                {editing === p.id ? "Close" : "Edit"}
              </button>
              <button
                className="btn-danger"
                onClick={() => {
                  if (window.confirm(`Remove ${p.name}?`))
                    act(() => api.providers.remove(p.id), `Removed ${p.name}`);
                }}
              >
                Remove
              </button>
            </span>
          </div>
          <div className="text-xs text-zinc-300 font-mono break-all">{p.base_url}</div>
          <div className="text-xs text-zinc-300">
            {p.has_api_key ? "API key set" : "no API key"} · timeout {p.timeout_s} s
            {p.tls_cert_name ? ` · verified against ${p.tls_cert_name}` : ""}
          </div>
          {p.last_result && (
            <div className="text-xs text-zinc-300">
              last test {p.last_tested_at}: {p.last_result}
            </div>
          )}

          {editing === p.id && (
            <div className="border-t border-zinc-600 pt-3">
              <ProviderForm
                initial={fromProvider(p)}
                certs={certs}
                isNew={false}
                hasKey={p.has_api_key}
                onCancel={() => setEditing(null)}
                onRemoveKey={() =>
                  act(
                    () => api.providers.update(p.id, { clear_api_key: true }),
                    `Removed ${p.name}'s API key`,
                  )
                }
                onSave={async (form) => {
                  const { api_key, ...rest } = form;
                  const ok = await act(
                    () =>
                      api.providers.update(p.id, api_key ? { ...rest, api_key } : rest),
                    `Saved ${form.name}`,
                  );
                  if (ok) setEditing(null);
                }}
              />
            </div>
          )}
        </div>
      ))}

      {providers.length === 0 && (
        <div className="text-xs text-zinc-300">
          No AI providers yet. Routines that use AI need one.
        </div>
      )}
    </div>
  );
}

function ToolsBadge({ provider }: { provider: Provider }) {
  if (!provider.supports_tools)
    return <span className="text-xs text-zinc-300">no tool calling</span>;
  if (provider.tools_ok === true)
    return <span className="text-xs text-emerald-400">tool calling works</span>;
  if (provider.tools_ok === false)
    return <span className="text-xs text-red-400">tool calling failed</span>;
  return <span className="text-xs text-zinc-300">tool calling not tested</span>;
}

function ProviderForm({
  initial,
  certs,
  isNew,
  hasKey,
  onSave,
  onCancel,
  onRemoveKey,
}: {
  initial: Form;
  certs: Certificate[];
  isNew: boolean;
  hasKey: boolean;
  onSave: (form: Form) => void;
  onCancel: () => void;
  onRemoveKey?: () => void;
}) {
  const [form, setForm] = useState<Form>(initial);
  const set = (change: Partial<Form>) => setForm((was) => ({ ...was, ...change }));

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-3 flex-wrap">
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Name</span>
          <input
            className="field w-48"
            placeholder="Local model"
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Kind</span>
          <select
            className="field w-52"
            value={form.kind}
            onChange={(e) => set({ kind: e.target.value as Form["kind"] })}
          >
            <option value="openai">OpenAI-compatible</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Model</span>
          <input
            className="field w-56 font-mono text-xs"
            placeholder="model name"
            value={form.model}
            onChange={(e) => set({ model: e.target.value })}
          />
        </label>
      </div>

      <label className="space-y-1 block">
        <span className="text-xs text-zinc-300">Base URL</span>
        <input
          className="field font-mono text-xs"
          placeholder={PLACEHOLDER[form.kind]}
          value={form.base_url}
          onChange={(e) => set({ base_url: e.target.value })}
        />
      </label>

      <div className="flex items-end gap-3 flex-wrap">
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">API key</span>
          <input
            className="field w-72"
            type="password"
            autoComplete="new-password"
            placeholder={hasKey ? "set — leave blank to keep it" : "none"}
            value={form.api_key}
            onChange={(e) => set({ api_key: e.target.value })}
          />
        </label>
        {!isNew && hasKey && onRemoveKey && (
          <button
            className="btn"
            onClick={() => {
              if (window.confirm("Remove the stored API key?")) onRemoveKey();
            }}
          >
            Remove key
          </button>
        )}
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Timeout (s)</span>
          <input
            className="field w-24"
            type="number"
            min={5}
            max={900}
            value={form.timeout_s}
            onChange={(e) => set({ timeout_s: Number(e.target.value) })}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-zinc-300">Certificate</span>
          <select
            className="field w-56"
            value={form.tls_cert_id}
            onChange={(e) => set({ tls_cert_id: Number(e.target.value) })}
          >
            <option value={0}>This host's trust store</option>
            {certs.map((cert) => (
              <option key={cert.id} value={cert.id}>
                {cert.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.supports_tools}
          onChange={(e) => set({ supports_tools: e.target.checked })}
        />
        This model supports tool calling
      </label>

      <div className="flex gap-2">
        <button
          className="btn-primary"
          disabled={!form.name.trim() || !form.base_url.trim() || !form.model.trim()}
          onClick={() => onSave(form)}
        >
          {isNew ? "Add provider" : "Save"}
        </button>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
