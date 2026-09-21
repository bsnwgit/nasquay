import { useEffect, useState } from "react";
import { api, type ApiToken } from "../api";
import Help from "./Help";

// Personal API tokens for outside AI tools, on the Account panel. A token is shown once,
// straight after it is made, and never again: only its hash is kept.

// The clipboard API can refuse — no permission, or a browser that withholds it — so the
// old selection-based copy is the fallback, and the caller is told which way it went.
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the fallback
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}

export default function ApiTokens({ isAdmin }: { isAdmin: boolean }) {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [form, setForm] = useState({ name: "", access: "read", allow_destructive: false, expires_days: 90 });
  const [made, setMade] = useState("");
  const [copied, setCopied] = useState<"" | "ok" | "failed">("");
  const [revoking, setRevoking] = useState<ApiToken | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [unavailable, setUnavailable] = useState(false);

  const load = () =>
    api.tokens
      .list()
      .then(setTokens)
      .catch(() => setUnavailable(true));

  useEffect(() => {
    load();
  }, []);

  if (unavailable) return null;

  const endpoint = `${window.location.origin}/mcp`;

  const create = async () => {
    setError("");
    setNote("");
    setMade("");
    setCopied("");
    try {
      const result = await api.tokens.create(form);
      setMade(result.token);
      setForm({ name: "", access: "read", allow_destructive: false, expires_days: 90 });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not make the token");
    }
  };

  const copy = async () => {
    const ok = await copyText(made);
    setCopied(ok ? "ok" : "failed");
    if (ok) window.setTimeout(() => setCopied(""), 3000);
  };

  const revoke = async (token: ApiToken) => {
    setError("");
    setNote("");
    try {
      await api.tokens.revoke(token.id);
      setRevoking(null);
      setNote(`Revoked ${token.name}`);
      await load();
    } catch (err) {
      setRevoking(null);
      setError(err instanceof Error ? err.message : "Could not revoke the token");
    }
  };

  return (
    <div className="card space-y-3">
      <div className="flex items-center gap-2">
        <div className="text-xs uppercase tracking-wide text-zinc-300">API tokens</div>
        <Help>
          <p>For AI tools outside NASQuay that speak MCP. Point the tool at <span className="font-mono">{endpoint}</span> with the header <span className="font-mono">Authorization: Bearer &lt;token&gt;</span>, transport streamable HTTP.</p>
          <p>A token acts as you and can never do more than your role allows. <span className="text-zinc-200">Read</span> tokens can only look; <span className="text-zinc-200">read and write</span> can change things too. Destructive actions are refused unless an administrator made the token to allow them.</p>
          <p>The token is shown once. NASQuay keeps only a hash of it, so a lost token cannot be recovered — revoke it and make another.</p>
          <p>Every call is in the audit log under your name and the token's.</p>
        </Help>
      </div>

      <div className="text-xs text-zinc-300 font-mono break-all">{endpoint}</div>

      {made && (
        <div className="space-y-1 border border-amber-500 p-2">
          <div className="text-xs text-amber-400">
            Copy it now. It will not be shown again.
          </div>
          <div className="font-mono text-xs break-all text-zinc-100 select-all">{made}</div>
          <div className="flex items-center gap-2">
            <button className="btn" onClick={copy}>
              {copied === "ok" ? "Copied" : "Copy"}
            </button>
            {copied === "ok" && <span className="text-xs text-emerald-400">Copied to the clipboard</span>}
            {copied === "failed" && (
              <span className="text-xs text-red-400">
                The browser would not copy it — select the token and copy it by hand
              </span>
            )}
          </div>
        </div>
      )}

      <div className="space-y-2">
        <input
          className="field"
          placeholder="what it is for"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <div className="flex gap-2">
          <select
            className="field"
            value={form.access}
            onChange={(e) =>
              setForm({
                ...form,
                access: e.target.value,
                allow_destructive: e.target.value === "write" && form.allow_destructive,
              })
            }
          >
            <option value="read">read only</option>
            <option value="write">read and write</option>
          </select>
          <select
            className="field"
            value={form.expires_days}
            onChange={(e) => setForm({ ...form, expires_days: Number(e.target.value) })}
          >
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>a year</option>
            <option value={0}>never expires</option>
          </select>
        </div>
        {isAdmin && form.access === "write" && (
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={form.allow_destructive}
              onChange={(e) => setForm({ ...form, allow_destructive: e.target.checked })}
            />
            allow destructive actions
          </label>
        )}
        <button className="btn-primary w-full" disabled={!form.name.trim()} onClick={create}>
          Make token
        </button>
        {error && <div className="text-sm text-red-400">{error}</div>}
        {note && !error && <div className="text-sm text-emerald-400">{note}</div>}
      </div>

      {tokens.map((t) => (
        <div key={t.id} className="text-xs border-t border-zinc-600 pt-2 space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-zinc-100">{t.name}</span>
            {isAdmin && <span className="text-zinc-300">{t.username}</span>}
            <button className="btn-danger ml-auto" onClick={() => setRevoking(t)}>
              Revoke
            </button>
          </div>
          <div className="text-zinc-300 font-mono">{t.prefix}…</div>
          <div className="text-zinc-300">
            {t.access === "read" ? "read only" : "read and write"}
            {t.allow_destructive && <span className="text-red-400"> · destructive</span>}
            {" · "}
            {t.expires_at ? `expires ${t.expires_at.slice(0, 10)}` : "never expires"}
            {" · "}
            {t.last_used_at ? `last used ${t.last_used_at}` : "never used"}
          </div>
        </div>
      ))}

      {revoking && (
        <RevokeDialog
          token={revoking}
          onCancel={() => setRevoking(null)}
          onConfirm={() => revoke(revoking)}
        />
      )}
    </div>
  );
}

function RevokeDialog({
  token,
  onCancel,
  onConfirm,
}: {
  token: ApiToken;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    // Above the account panel, which is itself an overlay. A click outside cancels.
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div
        role="alertdialog"
        aria-modal="true"
        className="card w-full max-w-sm space-y-3 border border-red-400"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="text-sm text-zinc-100">Revoke {token.name}?</div>
        <div className="text-xs text-zinc-300 font-mono">{token.prefix}…</div>
        <div className="text-sm text-red-400">
          This cannot be undone. The token is deleted, and anything using it stops working on its
          next call. To connect again, make a new token.
        </div>
        <div className="flex gap-2 justify-end">
          <button className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn-danger"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              onConfirm();
            }}
          >
            {busy ? "Revoking…" : "Revoke token"}
          </button>
        </div>
      </div>
    </div>
  );
}
