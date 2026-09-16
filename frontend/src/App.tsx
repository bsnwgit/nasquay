import { useEffect, useState } from "react";
import { api, refresh, setToken, type Session } from "./api";
import Login from "./pages/Login";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";
import Account from "./pages/Account";

const PAGES = ["Audit", "Settings"] as const;
type Page = (typeof PAGES)[number];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [starting, setStarting] = useState(true);
  const [page, setPage] = useState<Page>("Settings");
  const [accountOpen, setAccountOpen] = useState(false);
  const [version, setVersion] = useState("");

  // A reload has no access token, but the refresh cookie may still be good.
  useEffect(() => {
    (async () => {
      const restored = await refresh();
      setSession(restored);
      setStarting(false);
    })();
    api.health().then((h) => setVersion(h.version)).catch(() => setVersion(""));
  }, []);

  const signOut = async () => {
    try {
      await api.logout();
    } catch {
      // signing out locally matters more than the server's answer
    }
    setToken(null);
    setSession(null);
    setAccountOpen(false);
  };

  if (starting) {
    return <div className="p-8 text-sm text-zinc-500">Loading…</div>;
  }

  if (!session) {
    return <Login version={version} onSignedIn={setSession} />;
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-zinc-800 px-4 py-3 flex items-center gap-4 flex-wrap">
        <div className="font-semibold tracking-wide">
          NASQuay <span className="text-zinc-500 text-xs font-normal">{version}</span>
        </div>
        <nav className="flex gap-1 flex-wrap">
          {PAGES.map((name) => (
            <button
              key={name}
              onClick={() => setPage(name)}
              className={
                name === page
                  ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                  : "px-3 py-1 text-sm border border-transparent text-zinc-400 hover:text-zinc-100"
              }
            >
              {name}
            </button>
          ))}
        </nav>

        {/* The signed-in user is the way into their own account. */}
        <button
          className={
            accountOpen
              ? "ml-auto px-3 py-1 text-sm border border-amber-500 text-amber-400"
              : "ml-auto px-3 py-1 text-sm border border-zinc-700 text-zinc-300 hover:border-zinc-500"
          }
          onClick={() => setAccountOpen((open) => !open)}
          title="Your account"
        >
          {session.username}
          <span className="text-zinc-500"> · {session.role}</span>
        </button>
      </header>

      <main className="p-4 flex-1">
        {page === "Audit" && <Audit />}
        {page === "Settings" && <Settings />}
      </main>

      {accountOpen && (
        <Account session={session} onClose={() => setAccountOpen(false)} onSignOut={signOut} />
      )}
    </div>
  );
}
