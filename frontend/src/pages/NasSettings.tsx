import { useEffect, useState } from "react";
import { api, type Nas } from "../api";

// Adding a NAS is deliberately two steps: read the certificate it presents, look at the
// fingerprint, then save. Nobody trusts a certificate they have not seen.
export default function NasSettings() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    name: "",
    address: "",
    mcp_port: 8443,
    tls_mode: "pinned",
    tls_fingerprint: "",
    mcp_token: "",
    ssh_user: "",
    ssh_port: 22,
  });
  const [tokenFor, setTokenFor] = useState<number | null>(null);
  const [newToken, setNewToken] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [edit, setEdit] = useState<Record<string, unknown>>({});

  const load = async () => {
    setError("");
    try {
      setUnits(await api.nas.list());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the NAS list");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const run = async (what: string, action: () => Promise<unknown>) => {
    setError("");
    setNote("");
    try {
      await action();
      setNote(what);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
    }
  };

  const readFingerprint = async () => {
    setError("");
    setNote("");
    try {
      const seen = await api.nas.fingerprint(form.address, form.mcp_port);
      setForm({ ...form, tls_fingerprint: seen.fingerprint });
      setNote("Certificate read — check the fingerprint, then save.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the certificate");
    }
  };

  const startEdit = (nas: Nas) => {
    setEditing(nas.id);
    setEdit({
      name: nas.name,
      address: nas.address,
      mcp_port: nas.mcp_port,
      tls_mode: nas.tls_mode,
      tls_fingerprint: nas.tls_fingerprint,
      ssh_user: nas.ssh_user,
      ssh_port: nas.ssh_port,
    });
  };

  const readFingerprintFor = async () => {
    setError("");
    setNote("");
    try {
      const seen = await api.nas.fingerprint(String(edit.address), Number(edit.mcp_port));
      setEdit({ ...edit, tls_mode: "pinned", tls_fingerprint: seen.fingerprint });
      setNote("Certificate read — check the fingerprint, then save.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the certificate");
    }
  };

  const check = async (nas: Nas) => {
    setError("");
    setNote("");
    try {
      const result = await api.nas.check(nas.id);
      setNote(
        `${nas.name}: MCP ${result.mcp_ok ? "ok" : "failed"} — ${result.mcp_detail}` +
          (result.ssh_detail ? ` · SSH ${result.ssh_ok ? "ok" : "failed"} — ${result.ssh_detail}` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The check could not run");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-400">NAS units</h1>
        <button className="btn" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "Add NAS"}
        </button>
        {note && <span className="text-sm text-amber-400">{note}</span>}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {adding && (
        <form
          className="card space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            run("NAS added", async () => {
              await api.nas.create(form);
              setForm({
                name: "", address: "", mcp_port: 8443, tls_mode: "pinned",
                tls_fingerprint: "", mcp_token: "", ssh_user: "", ssh_port: 22,
              });
              setAdding(false);
            });
          }}
        >
          <div className="grid gap-3 md:grid-cols-4">
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">Name</span>
              <input className="field" value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">Address</span>
              <input className="field" placeholder="10.0.0.10" value={form.address}
                     onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">MCP port</span>
              <input className="field" type="number" min={1} max={65535} value={form.mcp_port}
                     onChange={(e) => setForm({ ...form, mcp_port: Number(e.target.value) })} />
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">Certificate</span>
              <select className="field" value={form.tls_mode}
                      onChange={(e) => setForm({ ...form, tls_mode: e.target.value })}>
                <option value="pinned">Pin this NAS's certificate</option>
                <option value="system">Trust the system's certificate store</option>
              </select>
            </label>
          </div>

          {form.tls_mode === "pinned" && (
            <div className="space-y-2">
              <div className="flex gap-2 items-end">
                <label className="space-y-1 flex-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">
                    Certificate fingerprint (SHA-256)
                  </span>
                  <input className="field font-mono text-xs" value={form.tls_fingerprint}
                         onChange={(e) => setForm({ ...form, tls_fingerprint: e.target.value })} />
                </label>
                <button type="button" className="btn" onClick={readFingerprint}
                        disabled={!form.address}>
                  Read from NAS
                </button>
              </div>
              <div className="text-xs text-zinc-500">
                Compare it with the certificate shown in the NAS's own admin pages before saving.
              </div>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-3">
            <label className="space-y-1 md:col-span-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">MCP token</span>
              <input className="field" type="password" value={form.mcp_token}
                     onChange={(e) => setForm({ ...form, mcp_token: e.target.value })} />
              <span className="block text-xs text-zinc-500">Stored encrypted; never shown again.</span>
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">SSH account</span>
              <input className="field" value={form.ssh_user}
                     onChange={(e) => setForm({ ...form, ssh_user: e.target.value })} />
              <span className="block text-xs text-zinc-500">Optional — for df, du and file counts.</span>
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">SSH port</span>
              <input className="field" type="number" min={1} max={65535} value={form.ssh_port}
                     onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })} />
            </label>
          </div>

          <button className="btn-primary" disabled={!form.name || !form.address}>
            Add NAS
          </button>
        </form>
      )}

      {units.length === 0 && (
        <div className="card text-sm text-zinc-500">No NAS units yet.</div>
      )}

      {units.map((nas) => (
        <div key={nas.id} className="card space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-sm">{nas.name}</div>
            <div className="text-xs text-zinc-500">
              {nas.address}:{nas.mcp_port} · {nas.tls_mode === "pinned" ? "pinned certificate" : "system trust"}
              {nas.ssh_user ? ` · ssh ${nas.ssh_user}:${nas.ssh_port}` : " · no ssh account"}
            </div>
            <div className="ml-auto flex gap-2">
              <button className="btn" onClick={() => check(nas)}>Test connection</button>
              <button className="btn" onClick={() => (editing === nas.id ? setEditing(null) : startEdit(nas))}>
                {editing === nas.id ? "Cancel" : "Edit"}
              </button>
              <button
                className={nas.enabled ? "btn-on" : "btn-off"}
                onClick={() =>
                  run(nas.enabled ? "NAS disabled" : "NAS enabled", () =>
                    api.nas.update(nas.id, { enabled: !nas.enabled }),
                  )
                }
              >
                {nas.enabled ? "Enabled" : "Disabled"}
              </button>
              <button className="btn" onClick={() => { setTokenFor(nas.id); setNewToken(""); }}>
                Replace token
              </button>
              <button
                className="btn-danger"
                onClick={() => {
                  if (window.confirm(`Remove ${nas.name} from NASQuay?`))
                    run("NAS removed", () => api.nas.remove(nas.id));
                }}
              >
                Remove
              </button>
            </div>
          </div>

          <div className="text-xs text-zinc-500">
            {nas.has_token ? "Token set" : "No token set"}
            {nas.last_checked_at && (
              <>
                {" · last checked "}
                {nas.last_checked_at}
                {" — "}
                <span className={nas.last_check_ok ? "text-zinc-400" : "text-red-400"}>
                  {nas.last_check_detail}
                </span>
              </>
            )}
          </div>

          {editing === nas.id && (
            <form
              className="space-y-3 border-t border-zinc-800 pt-3"
              onSubmit={(e) => {
                e.preventDefault();
                run("NAS updated", async () => {
                  await api.nas.update(nas.id, edit);
                  setEditing(null);
                });
              }}
            >
              <div className="grid gap-3 md:grid-cols-4">
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">Name</span>
                  <input className="field" value={String(edit.name ?? "")}
                         onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
                </label>
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">Address</span>
                  <input className="field" value={String(edit.address ?? "")}
                         onChange={(e) => setEdit({ ...edit, address: e.target.value })} />
                </label>
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">MCP port</span>
                  <input className="field" type="number" min={1} max={65535}
                         value={Number(edit.mcp_port ?? 8443)}
                         onChange={(e) => setEdit({ ...edit, mcp_port: Number(e.target.value) })} />
                </label>
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">Certificate</span>
                  <select className="field" value={String(edit.tls_mode ?? "pinned")}
                          onChange={(e) => setEdit({ ...edit, tls_mode: e.target.value })}>
                    <option value="pinned">Pin this NAS's certificate</option>
                    <option value="system">Trust the system's certificate store</option>
                  </select>
                </label>
              </div>

              {edit.tls_mode === "pinned" && (
                <div className="flex gap-2 items-end">
                  <label className="space-y-1 flex-1">
                    <span className="text-xs uppercase tracking-wide text-zinc-400">
                      Certificate fingerprint (SHA-256)
                    </span>
                    <input className="field font-mono text-xs" value={String(edit.tls_fingerprint ?? "")}
                           onChange={(e) => setEdit({ ...edit, tls_fingerprint: e.target.value })} />
                  </label>
                  <button type="button" className="btn" onClick={readFingerprintFor}>
                    Read from NAS
                  </button>
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-3">
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">SSH account</span>
                  <input className="field" value={String(edit.ssh_user ?? "")}
                         onChange={(e) => setEdit({ ...edit, ssh_user: e.target.value })} />
                  <span className="block text-xs text-zinc-500">
                    An account on the NAS, not NASQuay's key name.
                  </span>
                </label>
                <label className="space-y-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-400">SSH port</span>
                  <input className="field" type="number" min={1} max={65535}
                         value={Number(edit.ssh_port ?? 22)}
                         onChange={(e) => setEdit({ ...edit, ssh_port: Number(e.target.value) })} />
                </label>
              </div>

              <button className="btn-primary">Save changes</button>
            </form>
          )}

          {tokenFor === nas.id && (
            <form
              className="flex gap-2 items-end"
              onSubmit={(e) => {
                e.preventDefault();
                run("Token replaced", async () => {
                  await api.nas.update(nas.id, { mcp_token: newToken });
                  setTokenFor(null);
                  setNewToken("");
                });
              }}
            >
              <label className="space-y-1 flex-1">
                <span className="text-xs uppercase tracking-wide text-zinc-400">New MCP token</span>
                <input className="field" type="password" value={newToken}
                       onChange={(e) => setNewToken(e.target.value)} />
              </label>
              <button className="btn-primary" disabled={!newToken}>Save token</button>
              <button type="button" className="btn" onClick={() => setTokenFor(null)}>Cancel</button>
            </form>
          )}
        </div>
      ))}
    </div>
  );
}
