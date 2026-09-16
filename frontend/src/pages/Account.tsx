import { useEffect, useState } from "react";
import { api, type Session, type User } from "../api";

// Opened from the signed-in user's name in the header, rather than living as its own tab.
export default function Account({
  session,
  onClose,
  onSignOut,
}: {
  session: Session;
  onClose: () => void;
  onSignOut: () => void;
}) {
  const [me, setMe] = useState<User | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [onClose]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setNote("");
    try {
      await api.changeMyPassword(current, next);
      setCurrent("");
      setNext("");
      // Changing a password ends every session, this one included.
      setNote("Password changed. Sign in again.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the password");
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-sm h-full bg-zinc-950 border-l border-zinc-800 p-4 space-y-4 overflow-y-auto"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <h1 className="text-sm uppercase tracking-wide text-zinc-400">Account</h1>
          <button className="btn ml-auto" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="card text-sm space-y-1">
          <div>{session.username}</div>
          <div className="text-xs text-zinc-500">
            Role: {session.role}
            {session.is_admin ? " · admin" : ""}
          </div>
          {me && (
            <div className="text-xs text-zinc-500">
              {me.display_name && <div>{me.display_name}</div>}
              {me.email && <div>{me.email}</div>}
              <div>Last signed in: {me.last_login ?? "never"}</div>
              <div>Account created: {me.created_at}</div>
            </div>
          )}
        </div>

        <form className="card space-y-3" onSubmit={submit}>
          <div className="text-xs uppercase tracking-wide text-zinc-400">Change password</div>
          <input className="field" type="password" placeholder="current password" value={current}
                 onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
          <input className="field" type="password" placeholder="new password (10+ characters)"
                 value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
          {note && <div className="text-sm text-amber-400">{note}</div>}
          {error && <div className="text-sm text-red-400">{error}</div>}
          <button className="btn-primary w-full" disabled={!current || !next}>
            Change password
          </button>
        </form>

        <button className="btn w-full" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
