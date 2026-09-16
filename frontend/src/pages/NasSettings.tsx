import { useEffect, useState } from "react";
import { api, type Nas, type Tool } from "../api";

// One page for the NAS units. Each row collapses to its state and expands to everything
// about that box: its buttons, its settings, and the tools it offers.
export default function NasSettings() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    name: "", address: "", mcp_port: 8443, tls_mode: "pinned",
    tls_fingerprint: "", mcp_token: "", ssh_user: "", ssh_port: 22,
  });
  const [tokenFor, setTokenFor] = useState<number | null>(null);
  const [newToken, setNewToken] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [edit, setEdit] = useState<Record<string, unknown>>({});

  const load = async () => {
    setError("");
    try {
      const [nasList, toolList] = await Promise.all([api.nas.list(), api.tools.list()]);
      setUnits(nasList);
      setTools(toolList);
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

  const readFingerprint = async (address: string, port: number, into: "add" | "edit") => {
    setError("");
    setNote("");
    try {
      const seen = await api.nas.fingerprint(address, port);
      if (into === "add") setForm({ ...form, tls_fingerprint: seen.fingerprint });
      else setEdit({ ...edit, tls_mode: "pinned", tls_fingerprint: seen.fingerprint });
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

  const discover = async (nas: Nas) => {
    setError("");
    setNote("");
    setBusy(true);
    try {
      const result = await api.tools.discover(nas.id);
      setNote(
        `${result.nas}: ${result.found} tools, ${result.added} new` +
          (result.unreviewed ? `, ${result.unreviewed} unreviewed` : ""),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed");
    } finally {
      setBusy(false);
    }
  };

  const review = async (tool: Tool, classification: string, reviewed: boolean) => {
    setError("");
    setNote("");
    try {
      await api.tools.review(tool.action_id, { classification, reviewed });
      setNote(`${tool.tool_name}: ${classification}${reviewed ? ", reviewed" : ", unreviewed"}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  };

  const startEdit = (nas: Nas) => {
    setEditing(nas.id);
    setEdit({
      name: nas.name, address: nas.address, mcp_port: nas.mcp_port, tls_mode: nas.tls_mode,
      tls_fingerprint: nas.tls_fingerprint, ssh_user: nas.ssh_user, ssh_port: nas.ssh_port,
    });
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
            <div className="flex gap-2 items-end">
              <label className="space-y-1 flex-1">
                <span className="text-xs uppercase tracking-wide text-zinc-400">
                  Certificate fingerprint (SHA-256)
                </span>
                <input className="field font-mono text-xs" value={form.tls_fingerprint}
                       onChange={(e) => setForm({ ...form, tls_fingerprint: e.target.value })} />
              </label>
              <button type="button" className="btn" disabled={!form.address}
                      onClick={() => readFingerprint(form.address, form.mcp_port, "add")}>
                Read from NAS
              </button>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-3">
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">MCP token</span>
              <input className="field" type="password" value={form.mcp_token}
                     onChange={(e) => setForm({ ...form, mcp_token: e.target.value })} />
              <span className="block text-xs text-zinc-500">Stored encrypted; never shown again.</span>
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">SSH account</span>
              <input className="field" value={form.ssh_user}
                     onChange={(e) => setForm({ ...form, ssh_user: e.target.value })} />
              <span className="block text-xs text-zinc-500">An account on the NAS. Optional.</span>
            </label>
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-zinc-400">SSH port</span>
              <input className="field" type="number" min={1} max={65535} value={form.ssh_port}
                     onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })} />
            </label>
          </div>

          <button className="btn-primary" disabled={!form.name || !form.address}>Add NAS</button>
        </form>
      )}

      {units.length === 0 && <div className="card text-sm text-zinc-500">No NAS units yet.</div>}

      {units.map((nas) => {
        const mine = tools.filter((t) => t.nas.includes(nas.name));
        const unreviewed = mine.filter((t) => !t.reviewed);
        const expanded = open === nas.id;

        return (
          <div key={nas.id} className="card space-y-3">
            {/* Collapsed: what this box is and how it last answered. */}
            <button
              className="w-full flex items-center gap-3 text-left"
              onClick={() => setOpen(expanded ? null : nas.id)}
            >
              <span className="text-zinc-500 w-3">{expanded ? "▾" : "▸"}</span>
              <span className="text-sm">{nas.name}</span>
              <span className="text-xs text-zinc-500">
                {nas.address}:{nas.mcp_port}
                {nas.ssh_user ? ` · ssh ${nas.ssh_user}` : ""}
                {mine.length ? ` · ${mine.length} tools` : " · no tools discovered"}
              </span>
              <span className={nas.enabled ? "text-xs text-emerald-400" : "text-xs text-red-400"}>
                {nas.enabled ? "enabled" : "disabled"}
              </span>
              {unreviewed.length > 0 && (
                <span className="text-xs text-amber-400">{unreviewed.length} unreviewed</span>
              )}
              {nas.last_check_ok === false && <span className="text-xs text-red-400">last check failed</span>}
            </button>

            {expanded && (
              <div className="space-y-4 border-t border-zinc-800 pt-3">
                <div className="flex gap-2 flex-wrap">
                  <button className="btn" onClick={() => check(nas)}>Test connection</button>
                  <button className="btn" disabled={busy} onClick={() => discover(nas)}>
                    {busy ? "Asking…" : "Discover tools"}
                  </button>
                  <button className="btn" onClick={() => (editing === nas.id ? setEditing(null) : startEdit(nas))}>
                    {editing === nas.id ? "Cancel edit" : "Edit"}
                  </button>
                  <button
                    className={nas.enabled ? "btn-on" : "btn-off"}
                    onClick={() =>
                      run(nas.enabled ? "NAS disabled" : "NAS enabled", () =>
                        api.nas.update(nas.id, { enabled: !nas.enabled }))
                    }
                  >
                    {nas.enabled ? "Enabled" : "Disabled"}
                  </button>
                  <button className="btn" onClick={() => { setTokenFor(nas.id); setNewToken(""); }}>
                    Replace token
                  </button>
                  <button
                    className="btn-danger ml-auto"
                    onClick={() => {
                      if (window.confirm(`Remove ${nas.name} from NASQuay?`))
                        run("NAS removed", () => api.nas.remove(nas.id));
                    }}
                  >
                    Remove
                  </button>
                </div>

                <div className="text-xs text-zinc-500">
                  {nas.tls_mode === "pinned" ? "pinned certificate" : "system trust"} ·{" "}
                  {nas.has_token ? "token set" : "no token set"}
                  {nas.last_checked_at && (
                    <>
                      {" · last checked "}{nas.last_checked_at}{" — "}
                      <span className={nas.last_check_ok ? "text-zinc-400" : "text-red-400"}>
                        {nas.last_check_detail}
                      </span>
                    </>
                  )}
                </div>

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

                {editing === nas.id && (
                  <form
                    className="space-y-3"
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
                          <input className="field font-mono text-xs"
                                 value={String(edit.tls_fingerprint ?? "")}
                                 onChange={(e) => setEdit({ ...edit, tls_fingerprint: e.target.value })} />
                        </label>
                        <button type="button" className="btn"
                                onClick={() => readFingerprint(String(edit.address), Number(edit.mcp_port), "edit")}>
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

                {/* The tools this box offers, and how NASQuay classifies them. */}
                <div className="space-y-2">
                  <div className="text-xs uppercase tracking-wide text-zinc-400">
                    Tools ({mine.length})
                  </div>
                  {mine.length === 0 && (
                    <div className="text-sm text-zinc-500">
                      None discovered yet — use Discover tools above.
                    </div>
                  )}
                  {unreviewed.length > 0 && (
                    <div className="text-xs text-amber-400">
                      {unreviewed.length} unreviewed — offered to nobody, admin included, until
                      classified.
                    </div>
                  )}
                  {/* Two columns, one line each: 42 tools otherwise run far down the page.
                      The description is the row's hover text rather than a second line. */}
                  {[...new Set(mine.map((t) => t.category))].sort().map((category) => (
                    <div key={category}>
                      <div className="text-xs uppercase tracking-wide text-zinc-500 mt-3 mb-1">
                        {category}
                      </div>
                      {/* The divider is drawn on the grid, not the rows: a border on each
                          row would break into dashes wherever the two columns disagree on
                          height. A one-pixel background column runs the full height. */}
                      <div
                        className="grid md:grid-cols-2 gap-x-12 md:bg-[linear-gradient(to_right,transparent_calc(50%-0.5px),rgb(82_82_91)_calc(50%-0.5px),rgb(82_82_91)_calc(50%+0.5px),transparent_calc(50%+0.5px))]"
                      >
                        {mine
                          .filter((t) => t.category === category)
                          .map((tool) => (
                            <div
                              key={tool.action_id}
                              title={tool.description || "No description given"}
                              className="flex items-center gap-2 py-0.5 border-b border-zinc-800/40 last:border-0"
                            >
                              <span className="font-mono text-xs text-zinc-300 flex-1 truncate">
                                {tool.tool_name}
                              </span>
                              <select
                                className="bg-zinc-900 border border-zinc-700 text-xs px-1 py-0.5 text-zinc-200 focus:outline-none focus:border-amber-500"
                                value={tool.classification}
                                onChange={(e) => review(tool, e.target.value, tool.reviewed)}
                              >
                                <option value="read">read</option>
                                <option value="write">write</option>
                                <option value="destructive">destructive</option>
                              </select>
                              <button
                                className={
                                  tool.reviewed
                                    ? "text-xs px-2 py-0.5 border border-emerald-700 text-emerald-400 hover:bg-emerald-950"
                                    : "text-xs px-2 py-0.5 border border-red-700 text-red-400 hover:bg-red-950"
                                }
                                onClick={() => review(tool, tool.classification, !tool.reviewed)}
                                title={tool.reviewed ? "Reviewed — click to withdraw" : "Unreviewed — click to approve"}
                              >
                                {tool.reviewed ? "✓" : "!"}
                              </button>
                            </div>
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
