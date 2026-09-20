import { useEffect, useState, type ReactNode } from "react";
import { api, type Certificate, type HiddenItem, type Nas, type Tool } from "../api";
import Help from "../components/Help";

// One page for the NAS units. Each row collapses to its state and expands to everything
// about that box: its buttons, its settings, and the tools it offers.
//
// Everything inside an expanded row is under a heading. There is a lot on one row — three
// forms and up to 42 tools — and without the headings it reads as one undifferentiated
// column of fields.
function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2 border-b border-zinc-600 pb-1">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-amber-400">{title}</h3>
        {hint && <span className="text-xs text-zinc-300">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

// How a NAS is verified, as one choice. Two columns hold it — pinned or not, and which
// certificate — but they are one decision to whoever is making it.
type Verify = "pinned" | "trusted" | "system";

const verifyOf = (tlsMode: string, certId: number | null | undefined): Verify =>
  tlsMode === "pinned" ? "pinned" : certId ? "trusted" : "system";

function VerifyChoice({
  value,
  certificates,
  certId,
  onChange,
}: {
  value: Verify;
  certificates: Certificate[];
  certId: number | null;
  onChange: (verify: Verify, certId: number | null) => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <label className="space-y-1">
        <span className="text-xs uppercase tracking-wide text-zinc-300">How it is verified</span>
        <select
          className="field"
          value={value}
          onChange={(e) => {
            const next = e.target.value as Verify;
            onChange(next, next === "trusted" ? certId ?? certificates[0]?.id ?? null : null);
          }}
        >
          <option value="pinned">Pin this NAS's certificate</option>
          <option value="trusted" disabled={certificates.length === 0}>
            Verify against an uploaded certificate
          </option>
          <option value="system">Trust the host's certificate store</option>
        </select>
        {certificates.length === 0 && (
          <span className="block text-xs text-zinc-300">
            Upload one in Settings → Certificates to use the middle option.
          </span>
        )}
      </label>

      {value === "trusted" && (
        <label className="space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-300">Certificate</span>
          <select
            className="field"
            value={certId ?? ""}
            onChange={(e) => onChange("trusted", Number(e.target.value) || null)}
          >
            {certificates.map((cert) => (
              <option key={cert.id} value={cert.id}>
                {cert.name} — {cert.subject}
              </option>
            ))}
          </select>
          <span className="block text-xs text-zinc-300">
            The name is checked, so this NAS's address must be one the certificate covers.
          </span>
        </label>
      )}
    </div>
  );
}

export default function NasSettings() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [certificates, setCertificates] = useState<Certificate[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    name: "", address: "", mcp_port: 8443, tls_mode: "pinned", tls_cert_id: null as number | null,
    tls_fingerprint: "", mcp_token: "", ssh_user: "", ssh_port: 22, admin_url: "",
  });
  // What each NAS hides, and the share list to tick against, loaded when a row is opened
  // — the share list is a call to the NAS, so it is not made for rows nobody looked at.
  const [hidden, setHidden] = useState<Record<number, HiddenItem[]>>({});
  const [shareNames, setShareNames] = useState<Record<number, string[]>>({});
  const [newPath, setNewPath] = useState("");
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
    // A role that may not see the certificates still gets a working page; it simply
    // cannot choose one.
    api.certificates.list().then(setCertificates).catch(() => setCertificates([]));
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

  // Ticking a box changes only this list — the share list itself is a call to the NAS,
  // and re-reading it would make a checkbox take as long as the NAS takes to answer.
  const refreshHidden = async (nasId: number) => {
    try {
      const items = await api.nas.hidden(nasId);
      setHidden((was) => ({ ...was, [nasId]: items }));
    } catch {
      // A role that may not read the NAS list has nothing to show here either.
    }
  };

  const loadHidden = async (nasId: number) => {
    await refreshHidden(nasId);
    // Both listings, because they do not agree on what is at the root: QTS's File Station
    // shows entries list_shared_folder never returns — `home` on the system volume, for
    // one — and a box that only knew about shared folders would offer no way to hide them.
    // Each listing arrives already filtered, so a hidden entry is absent from both; the
    // hidden rows are what say which those are.
    try {
      const [shares, root] = await Promise.all([
        api.run(nasId, "list_shared_folder", {}),
        api.run(nasId, "list_files", { path: "/", limit: 200 }),
      ]);
      const shareData = (shares.json_result ?? {}) as { sharedfolders?: { name?: string }[] };
      const rootData = (root.json_result ?? {}) as { data?: { name?: string }[] };
      const names = [
        ...(shareData.sharedfolders ?? []).map((share) => share.name ?? ""),
        ...(rootData.data ?? []).map((entry) => entry.name ?? ""),
      ].filter(Boolean);
      const unique = new Map<string, string>();
      for (const name of names) unique.set(name.toLowerCase(), name);
      setShareNames((was) => ({ ...was, [nasId]: [...unique.values()] }));
    } catch {
      setShareNames((was) => ({ ...was, [nasId]: [] }));
    }
  };

  const openRow = (nas: Nas, expanded: boolean) => {
    setOpen(expanded ? null : nas.id);
    if (!expanded && hidden[nas.id] === undefined) loadHidden(nas.id);
  };

  const startEdit = (nas: Nas) => {
    setEditing(nas.id);
    setEdit({
      name: nas.name, address: nas.address, mcp_port: nas.mcp_port, tls_mode: nas.tls_mode,
      tls_cert_id: nas.tls_cert_id, tls_fingerprint: nas.tls_fingerprint,
      ssh_user: nas.ssh_user, ssh_port: nas.ssh_port, admin_url: nas.admin_url,
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">NAS units</h1>
        <Help>
          <p>The NAS units NASQuay can reach, and how it reaches them.</p>
          <p>A NAS is verified one of three ways: its certificate is pinned, it is checked against a certificate uploaded in Settings → Certificates, or it is checked against the host's own trust store. Pinning is two steps on purpose — read the certificate it presents, then save it — so an admin sees what they are trusting, and a substituted certificate is refused rather than accepted.</p>
          <p>Tokens go in but never come out — the API reports only whether one is set. Leaving the field empty when editing keeps the stored token.</p>
        </Help>
        <button className="btn" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "Add NAS"}
        </button>
        {note && <span className="text-sm text-amber-400">{note}</span>}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {adding && (
        <form
          className="card space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            run("NAS added", async () => {
              await api.nas.create(form);
              setForm({
                name: "", address: "", mcp_port: 8443, tls_mode: "pinned", tls_cert_id: null,
                tls_fingerprint: "", mcp_token: "", ssh_user: "", ssh_port: 22, admin_url: "",
              });
              setAdding(false);
            });
          }}
        >
          <Section title="The NAS" hint="where MCP Assistant answers">
            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">Name</span>
                <input className="field" value={form.name}
                       onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">Address</span>
                <input className="field" placeholder="10.0.0.10" value={form.address}
                       onChange={(e) => setForm({ ...form, address: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">MCP port</span>
                <input className="field" type="number" min={1} max={65535} value={form.mcp_port}
                       onChange={(e) => setForm({ ...form, mcp_port: Number(e.target.value) })} />
              </label>
            </div>
          </Section>

          <Section title="Certificate" hint="how NASQuay knows it is talking to this NAS">
            <VerifyChoice
              value={verifyOf(form.tls_mode, form.tls_cert_id)}
              certificates={certificates}
              certId={form.tls_cert_id}
              onChange={(verify, certId) =>
                setForm({
                  ...form,
                  tls_mode: verify === "pinned" ? "pinned" : "system",
                  tls_cert_id: certId,
                })
              }
            />

            {form.tls_mode === "pinned" && (
              <div className="flex gap-2 items-end">
                <label className="space-y-1 flex-1">
                  <span className="text-xs uppercase tracking-wide text-zinc-300">
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
          </Section>

          <Section title="Credentials" hint="stored on this host, never shown again">
            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">MCP token</span>
                <input className="field" type="password" value={form.mcp_token}
                       onChange={(e) => setForm({ ...form, mcp_token: e.target.value })} />
                <span className="block text-xs text-zinc-300">Stored encrypted; never shown again.</span>
              </label>
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">SSH account</span>
                <input className="field" value={form.ssh_user}
                       onChange={(e) => setForm({ ...form, ssh_user: e.target.value })} />
                <span className="block text-xs text-zinc-300">An account on the NAS. Optional.</span>
              </label>
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-zinc-300">SSH port</span>
                <input className="field" type="number" min={1} max={65535} value={form.ssh_port}
                       onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })} />
              </label>
            </div>
          </Section>

          <Section title="Home page link" hint="what the home page opens for this NAS">
            <label className="space-y-1 block">
              <span className="text-xs uppercase tracking-wide text-zinc-300">
                Link to this NAS's own interface
              </span>
              <input className="field" placeholder="https://nas.example.com:8080"
                     value={form.admin_url}
                     onChange={(e) => setForm({ ...form, admin_url: e.target.value })} />
              <span className="block text-xs text-zinc-300">
                Whatever address you use yourself — <code>http</code> or <code>https</code>, a
                name or an IP address, any port. Left empty, the home page falls back to
                <code> https://{form.address || "the address above"}</code>. NASQuay never
                fetches it; the link simply opens in a new tab.
              </span>
            </label>
          </Section>

          <button className="btn-primary" disabled={!form.name || !form.address}>Add NAS</button>
        </form>
      )}

      {units.length === 0 && <div className="card text-sm text-zinc-300">No NAS units yet.</div>}

      {units.map((nas) => {
        const mine = tools.filter((t) => t.nas.includes(nas.name));
        const unreviewed = mine.filter((t) => !t.reviewed);
        const expanded = open === nas.id;
        const editVerify = verifyOf(
          String(edit.tls_mode ?? "pinned"),
          (edit.tls_cert_id as number | null) ?? null,
        );

        return (
          <div key={nas.id} className="card space-y-3">
            {/* Collapsed: what this box is and how it last answered. */}
            <button
              className="w-full flex items-center gap-3 text-left"
              onClick={() => openRow(nas, expanded)}
            >
              <span className="text-zinc-300 w-3">{expanded ? "▾" : "▸"}</span>
              <span className="text-sm">{nas.name}</span>
              <span className="text-xs text-zinc-300">
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
              <div className="space-y-5 border-t border-zinc-600 pt-3">
                <Section title="Actions">
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
                </Section>

                <Section title="State">
                  <div className="text-xs text-zinc-300">
                    {nas.tls_mode === "pinned"
                      ? "pinned certificate"
                      : nas.tls_cert_name
                        ? `verified against ${nas.tls_cert_name}`
                        : "host trust store"}{" "}
                    · {nas.has_token ? "token set" : "no token set"}
                    {" · home page link "}
                    <a href={nas.admin_url || `https://${nas.address}`} target="_blank"
                       rel="noreferrer noopener" className="text-amber-400 hover:underline">
                      {nas.admin_url || `https://${nas.address}`} ↗
                    </a>
                    {!nas.admin_url && " (the default — set your own under Edit)"}
                    {nas.last_checked_at && (
                      <>
                        {" · last checked "}{nas.last_checked_at}{" — "}
                        <span className={nas.last_check_ok ? "text-zinc-300" : "text-red-400"}>
                          {nas.last_check_detail}
                        </span>
                      </>
                    )}
                  </div>
                </Section>

                {tokenFor === nas.id && (
                  <Section title="MCP token" hint="replacing it; the stored one is never shown">
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
                        <span className="text-xs uppercase tracking-wide text-zinc-300">New MCP token</span>
                        <input className="field" type="password" value={newToken}
                               onChange={(e) => setNewToken(e.target.value)} />
                      </label>
                      <button className="btn-primary" disabled={!newToken}>Save token</button>
                      <button type="button" className="btn" onClick={() => setTokenFor(null)}>Cancel</button>
                    </form>
                  </Section>
                )}

                {editing === nas.id && (
                  <form
                    className="space-y-5"
                    onSubmit={(e) => {
                      e.preventDefault();
                      run("NAS updated", async () => {
                        // 0 rather than null: the server reads "not sent" as "leave it
                        // alone", so clearing the certificate has to be said out loud.
                        await api.nas.update(nas.id, { ...edit, tls_cert_id: edit.tls_cert_id ?? 0 });
                        setEditing(null);
                      });
                    }}
                  >
                    <Section title="The NAS" hint="where MCP Assistant answers">
                      <div className="grid gap-3 md:grid-cols-3">
                        <label className="space-y-1">
                          <span className="text-xs uppercase tracking-wide text-zinc-300">Name</span>
                          <input className="field" value={String(edit.name ?? "")}
                                 onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
                        </label>
                        <label className="space-y-1">
                          <span className="text-xs uppercase tracking-wide text-zinc-300">Address</span>
                          <input className="field" value={String(edit.address ?? "")}
                                 onChange={(e) => setEdit({ ...edit, address: e.target.value })} />
                        </label>
                        <label className="space-y-1">
                          <span className="text-xs uppercase tracking-wide text-zinc-300">MCP port</span>
                          <input className="field" type="number" min={1} max={65535}
                                 value={Number(edit.mcp_port ?? 8443)}
                                 onChange={(e) => setEdit({ ...edit, mcp_port: Number(e.target.value) })} />
                        </label>
                      </div>
                    </Section>

                    <Section title="Certificate" hint="how NASQuay knows it is talking to this NAS">
                      <VerifyChoice
                        value={editVerify}
                        certificates={certificates}
                        certId={(edit.tls_cert_id as number | null) ?? null}
                        onChange={(verify, certId) =>
                          setEdit({
                            ...edit,
                            tls_mode: verify === "pinned" ? "pinned" : "system",
                            tls_cert_id: certId,
                          })
                        }
                      />

                      {edit.tls_mode === "pinned" && (
                        <div className="flex gap-2 items-end">
                          <label className="space-y-1 flex-1">
                            <span className="text-xs uppercase tracking-wide text-zinc-300">
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
                    </Section>

                    <Section title="Credentials" hint="the token is replaced from Actions, above">
                      <div className="grid gap-3 md:grid-cols-3">
                        <label className="space-y-1">
                          <span className="text-xs uppercase tracking-wide text-zinc-300">SSH account</span>
                          <input className="field" value={String(edit.ssh_user ?? "")}
                                 onChange={(e) => setEdit({ ...edit, ssh_user: e.target.value })} />
                          <span className="block text-xs text-zinc-300">
                            An account on the NAS, not NASQuay's key name.
                          </span>
                        </label>
                        <label className="space-y-1">
                          <span className="text-xs uppercase tracking-wide text-zinc-300">SSH port</span>
                          <input className="field" type="number" min={1} max={65535}
                                 value={Number(edit.ssh_port ?? 22)}
                                 onChange={(e) => setEdit({ ...edit, ssh_port: Number(e.target.value) })} />
                        </label>
                      </div>
                    </Section>

                    <Section title="Home page link" hint="what the home page opens for this NAS">
                      <label className="space-y-1 block">
                        <span className="text-xs uppercase tracking-wide text-zinc-300">
                          Link to this NAS's own interface
                        </span>
                        <input className="field" placeholder="https://nas.example.com:8080"
                               value={String(edit.admin_url ?? "")}
                               onChange={(e) => setEdit({ ...edit, admin_url: e.target.value })} />
                        <span className="block text-xs text-zinc-300">
                          Whatever address you use yourself — <code>http</code> or
                          <code> https</code>, a name or an IP address, any port. Emptying it
                          falls back to <code>https://{String(edit.address ?? nas.address)}</code>.
                        </span>
                      </label>
                    </Section>

                    <button className="btn-primary">Save changes</button>
                  </form>
                )}

                <Section
                  title="What is shown"
                  hint="presentation only — hiding grants and withholds nothing"
                >
                  {(() => {
                    const items = hidden[nas.id] ?? [];
                    const hiddenShares = items.filter((i) => i.kind === "share");
                    const hiddenPaths = items.filter((i) => i.kind === "path");
                    const visible = shareNames[nas.id] ?? [];
                    const change = (what: string, action: () => Promise<unknown>) =>
                      run(what, async () => {
                        await action();
                        await refreshHidden(nas.id);
                      });

                    // One row per share, hidden or not. The two sources overlap for as
                    // long as it takes the NAS to answer again — the listing still holds
                    // a share that has just been hidden — so they are merged by name
                    // rather than concatenated, and the hidden list wins.
                    const rows = new Map<string, { name: string; shown: boolean }>();
                    for (const name of visible) rows.set(name.toLowerCase(), { name, shown: true });
                    for (const item of hiddenShares)
                      rows.set(item.value.toLowerCase(), { name: item.value, shown: false });

                    return (
                      <div className="space-y-4">
                        <div className="space-y-1">
                          <div className="text-xs text-zinc-300">
                            Everything at the top of this NAS — its shared folders, and
                            anything else File Station lists there. Unticked ones are left
                            out of the Shares page and of the top level of Files.
                          </div>
                          <div className="grid md:grid-cols-3 gap-x-6">
                            {[...rows.values()]
                              .sort((a, b) => a.name.localeCompare(b.name))
                              .map((share) => (
                                <label key={share.name} className="flex items-center gap-2 py-0.5 text-sm">
                                  <input
                                    type="checkbox"
                                    checked={share.shown}
                                    onChange={() =>
                                      share.shown
                                        ? change(`${share.name} hidden`, () =>
                                            api.nas.hide(nas.id, "share", share.name))
                                        : change(`${share.name} shown`, async () => {
                                            await api.nas.show(
                                              nas.id,
                                              hiddenShares.find((i) => i.value === share.name)!.id,
                                            );
                                            // Put it back in the listing here too, or the
                                            // row would vanish until the NAS is read again.
                                            setShareNames((was) => ({
                                              ...was,
                                              [nas.id]: [...(was[nas.id] ?? []), share.name],
                                            }));
                                          })
                                    }
                                  />
                                  <span className={share.shown ? "text-zinc-200" : "text-zinc-400 line-through"}>
                                    {share.name}
                                  </span>
                                </label>
                              ))}
                            {rows.size === 0 && (
                              <div className="text-sm text-zinc-300">
                                No shares read from this NAS yet.
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="space-y-1">
                          <div className="text-xs text-zinc-300">
                            Folders hidden at one place in the tree, as File Station spells
                            them. A folder name to hide in every share, on every NAS, belongs
                            in Settings → General instead.
                          </div>
                          {hiddenPaths.map((item) => (
                            <div key={item.id} className="flex items-center gap-2 py-0.5">
                              <span className="font-mono text-xs text-zinc-200 flex-1 truncate">
                                {item.value}
                              </span>
                              <button
                                className="btn"
                                onClick={() => change(`${item.value} shown`, () => api.nas.show(nas.id, item.id))}
                              >
                                Show
                              </button>
                            </div>
                          ))}
                          <form
                            className="flex gap-2 items-end pt-1"
                            onSubmit={(e) => {
                              e.preventDefault();
                              const value = newPath;
                              change(`${value} hidden`, async () => {
                                await api.nas.hide(nas.id, "path", value);
                                setNewPath("");
                              });
                            }}
                          >
                            <label className="space-y-1 flex-1">
                              <span className="text-xs uppercase tracking-wide text-zinc-300">
                                Hide a folder
                              </span>
                              <input className="field font-mono text-xs" placeholder="/Series-B/@Recycle"
                                     value={newPath} onChange={(e) => setNewPath(e.target.value)} />
                            </label>
                            <button className="btn" disabled={!newPath.trim()}>Hide</button>
                          </form>
                        </div>
                      </div>
                    );
                  })()}
                </Section>

                {/* The tools this box offers, and how NASQuay classifies them. */}
                <Section
                  title={`Tools (${mine.length})`}
                  hint={unreviewed.length > 0 ? `${unreviewed.length} unreviewed` : undefined}
                >
                  {mine.length === 0 && (
                    <div className="text-sm text-zinc-300">
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
                      {/* A category is a heading under a heading, so it is the secondary
                          channel — ice blue against the section's gold — rather than a
                          third weight of grey nobody can pick out. */}
                      <div className="mt-4 mb-2 flex items-center gap-2">
                        <span className="text-[11px] font-semibold uppercase tracking-widest text-sky-300 bg-zinc-800 border-l-2 border-sky-400 px-2 py-1">
                          {category}
                        </span>
                        <span className="text-xs text-zinc-400">
                          {mine.filter((t) => t.category === category).length}
                        </span>
                        <span className="h-px flex-1 bg-zinc-700" />
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
                              className="flex items-center gap-2 py-0.5 border-b border-zinc-600/40 last:border-0"
                            >
                              <span className="font-mono text-xs text-zinc-200 flex-1 truncate">
                                {tool.tool_name}
                              </span>
                              <select
                                className="bg-zinc-900 border border-zinc-600 text-xs px-1 py-0.5 text-zinc-200 focus:outline-none focus:border-amber-500"
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
                </Section>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
