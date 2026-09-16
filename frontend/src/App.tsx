import { useEffect, useState } from "react";
import { api, refresh, setToken, type Session } from "./api";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Storage from "./pages/Storage";
import Shares from "./pages/Shares";
import Files from "./pages/Files";
import Accounts from "./pages/Accounts";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";
import Account from "./pages/Account";
import { LogoMark } from "./components/Logo";

const PAGES = ["Home", "Storage", "Shares", "Files", "Accounts", "Audit", "Settings"] as const;
type Page = (typeof PAGES)[number];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [starting, setStarting] = useState(true);
  const [page, setPage] = useState<Page>("Home");
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
        {/* The mark is also the way home. */}
        <button
          onClick={() => setPage("Home")}
          className="flex items-center gap-2 font-semibold tracking-wide"
          title="Home"
        >
          <LogoMark className="h-6 w-6" />
          <span>
            NAS<span className="text-amber-400">Quay</span>
          </span>
          <span className="text-zinc-500 text-xs font-normal">{version}</span>
        </button>
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
        {page === "Home" && (
          <Home username={session.username} version={version} onGo={setPage} />
        )}
        {page === "Storage" && <Storage />}
        {page === "Shares" && <Shares />}
        {page === "Files" && <Files />}
        {page === "Accounts" && <Accounts />}
        {page === "Audit" && <Audit />}
        {page === "Settings" && <Settings />}
      </main>

      {accountOpen && (
        <Account session={session} onClose={() => setAccountOpen(false)} onSignOut={signOut} />
      )}
    </div>
  );
}
