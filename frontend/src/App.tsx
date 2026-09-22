import { useEffect, useState } from "react";
import { api, refresh, setToken, type Session } from "./api";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Storage from "./pages/Storage";
import Shares from "./pages/Shares";
import Files from "./pages/Files";
import ResonanceMount from "./resonance/ResonanceMount";
import Accounts from "./pages/Accounts";
import Logs from "./pages/Logs";
import System from "./pages/System";
import Security from "./pages/Security";
import Monitoring from "./pages/Monitoring";
import Dashboard from "./pages/Dashboard";
import ClientMonitoring from "./pages/ClientMonitoring";
import StorageOverview from "./pages/StorageOverview";
import SystemOverview from "./pages/SystemOverview";
import Audit from "./pages/Audit";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Account from "./pages/Account";
import { LogoMark } from "./components/Logo";
import { setTimezone } from "./utils/format";

// The top menu is groups, not pages: eleven items across the top was a list to search
// rather than a place to go. A group opens on its first page and keeps its own left nav.
const GROUPS = [
  { name: "Home", pages: ["Home"] },
  { name: "Storage", pages: ["StorageOverview", "Storage", "Shares", "Files"] },
  { name: "Activity", pages: ["Dashboard", "Monitoring", "ClientMonitoring", "Reports", "Logs", "Audit"] },
  { name: "System", pages: ["SystemOverview", "Accounts", "System", "Security"] },
  { name: "Settings", pages: ["Settings"] },
] as const;

type Page =
  | "Home" | "StorageOverview" | "Storage" | "Shares" | "Files"
  | "Dashboard" | "Monitoring" | "ClientMonitoring" | "Reports" | "Logs" | "Audit"
  | "SystemOverview"
  | "Accounts" | "System" | "Security" | "Settings";

// A sub-tab's label is not always its page name: "Storage > Storage" said nothing.
const LABELS: Partial<Record<Page, string>> = {
  Storage: "Pools",
  StorageOverview: "Overview",
  SystemOverview: "Overview",
  Monitoring: "NAS",
  ClientMonitoring: "Clients",
};

const groupOf = (page: Page) =>
  GROUPS.find((one) => (one.pages as readonly string[]).includes(page)) ?? GROUPS[0];

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
    api
      .health()
      .then((h) => {
        setVersion(h.version);
        setTimezone(h.timezone);
      })
      .catch(() => setVersion(""));
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
    return <div className="p-8 text-sm text-zinc-300">Loading…</div>;
  }

  if (!session) {
    return <Login version={version} onSignedIn={setSession} />;
  }

  const show = (which: Page) => {
    switch (which) {
      case "Home":
        return <Home username={session.username} version={version} onGo={setPage} />;
      case "StorageOverview":
        return <StorageOverview />;
      case "Storage":
        return <Storage />;
      case "Shares":
        return <Shares />;
      case "Files":
        return <Files isAdmin={session.is_admin} />;
      case "Accounts":
        return <Accounts />;
      case "Logs":
        return <Logs />;
      case "SystemOverview":
        return <SystemOverview />;
      case "System":
        return <System />;
      case "Security":
        return <Security />;
      case "Dashboard":
        return <Dashboard />;
      case "Monitoring":
        return <Monitoring />;
      case "ClientMonitoring":
        return <ClientMonitoring />;
      case "Reports":
        return <Reports />;
      case "Audit":
        return <Audit />;
      case "Settings":
        return <Settings />;
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-zinc-600 px-4 py-3 flex items-center gap-4 flex-wrap">
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
          <span className="text-zinc-300 text-xs font-normal">{version}</span>
        </button>
        <nav className="flex gap-1 flex-wrap">
          {GROUPS.map((one) => (
            <button
              key={one.name}
              onClick={() => setPage(one.pages[0] as Page)}
              className={
                one.name === groupOf(page).name
                  ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                  : "px-3 py-1 text-sm border border-transparent text-zinc-300 hover:text-zinc-100"
              }
            >
              {one.name}
            </button>
          ))}
        </nav>

        {/* The signed-in user is the way into their own account. */}
        <button
          className={
            accountOpen
              ? "ml-auto px-3 py-1 text-sm border border-amber-500 text-amber-400"
              : "ml-auto px-3 py-1 text-sm border border-zinc-600 text-zinc-200 hover:border-zinc-500"
          }
          onClick={() => setAccountOpen((open) => !open)}
          title="Your account"
        >
          {session.username}
          <span className="text-zinc-300"> · {session.role}</span>
        </button>
      </header>

      <main className="p-4 flex-1">
        {/* A group with one page is just that page; the rest get a left nav of their own,
            the same shape Settings already uses. */}
        {groupOf(page).pages.length === 1 ? (
          show(page)
        ) : (
          <div className="grid gap-4 md:grid-cols-[12rem_1fr]">
            <nav className="card h-fit space-y-1">
              <div className="text-xs uppercase tracking-wide text-zinc-300 pb-1">
                {groupOf(page).name}
              </div>
              {groupOf(page).pages.map((name) => (
                <button
                  key={name}
                  onClick={() => setPage(name as Page)}
                  className={
                    name === page
                      ? "w-full text-left px-2 py-1 text-sm border border-amber-500 text-amber-400"
                      : "w-full text-left px-2 py-1 text-sm border border-transparent text-zinc-200 hover:border-zinc-600"
                  }
                >
                  {LABELS[name as Page] ?? name}
                </button>
              ))}
            </nav>
            <div>{show(page)}</div>
          </div>
        )}
      </main>

      {accountOpen && (
        <Account session={session} onClose={() => setAccountOpen(false)} onSignOut={signOut} />
      )}

      {/* Once, inside the signed-in layout — never per page. Every mount costs a session
          code, and a remount discards the conversation that was running. */}
      <ResonanceMount />
    </div>
  );
}
