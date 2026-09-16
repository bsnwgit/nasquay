import { useState } from "react";
import { api, type Session } from "../api";
import { LogoMark } from "../components/Logo";

export default function Login({
  version,
  onSignedIn,
}: {
  version: string;
  onSignedIn: (session: Session) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await api.login(username, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-3">
          <LogoMark className="h-10 w-10 shrink-0" />
          <div>
            <div className="text-lg font-semibold tracking-wide">
              NAS<span className="text-amber-400">Quay</span>
            </div>
            <div className="text-xs text-zinc-500">{version}</div>
          </div>
        </div>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Username</span>
          <input
            className="field"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Password</span>
          <input
            className="field"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && <div className="text-sm text-red-400">{error}</div>}

        <button className="btn-primary w-full" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
