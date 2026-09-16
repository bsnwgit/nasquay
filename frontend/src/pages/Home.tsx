import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import { LogoMark } from "../components/Logo";
import { when } from "../utils/format";

// The landing page. Deliberately cheap: it lists the NAS units NASQuay already knows
// about and what happened the last time each was checked. Nothing here contacts a NAS,
// so opening the app does not wake two boxes up.

type Page = "Storage" | "Shares" | "Files" | "Accounts" | "Logs" | "System" | "Security" | "Audit" | "Settings";

const LINKS: { page: Page; label: string; blurb: string }[] = [
  { page: "Storage", label: "Storage", blurb: "Pools, volumes and disks" },
  { page: "Shares", label: "Shares", blurb: "Shared folders, permissions and NFS exports" },
  { page: "Files", label: "Files", blurb: "Browse what is actually on a share" },
  { page: "Accounts", label: "Accounts", blurb: "The NAS's own users, groups and sessions" },
  { page: "Logs", label: "Logs", blurb: "The NAS's event and access logs" },
  { page: "System", label: "System", blurb: "Firmware, load, temperatures and applications" },
  { page: "Security", label: "Security", blurb: "What the NAS's own security applications report" },
  { page: "Audit", label: "Audit", blurb: "Every action NASQuay has taken" },
  { page: "Settings", label: "Settings", blurb: "NAS units, users, roles and the app itself" },
];

export default function Home({
  username,
  version,
  onGo,
}: {
  username: string;
  version: string;
  onGo: (page: Page) => void;
}) {
  const [units, setUnits] = useState<Nas[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.nas
      .list()
      .then(setUnits)
      // A role that may not list NAS units still gets a usable landing page.
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"));
  }, []);

  return (
    <div className="max-w-5xl mx-auto space-y-10 py-8">
      <div className="flex items-center gap-5">
        <LogoMark className="h-20 w-20 shrink-0" />
        <div className="space-y-1">
          <div className="text-4xl font-semibold tracking-wide">
            NAS<span className="text-amber-400">Quay</span>
          </div>
          <div className="text-sm text-zinc-400">
            Welcome back, {username}.{version && <span className="text-zinc-600"> · {version}</span>}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-xs uppercase tracking-wide text-zinc-500">Your NAS units</h2>

        {error && <div className="card text-sm text-zinc-500">{error}</div>}

        {!error && units.length === 0 && (
          <div className="card text-sm text-zinc-500">
            No NAS units yet. Add one in Settings → NAS.
          </div>
        )}

        <div className="grid md:grid-cols-2 gap-3">
          {units.map((nas) => (
            <div key={nas.id} className="card space-y-2">
              <div className="flex items-center gap-3">
                <span
                  className={
                    nas.enabled && nas.last_check_ok
                      ? "h-2 w-2 bg-emerald-400 shrink-0"
                      : nas.enabled
                        ? "h-2 w-2 bg-zinc-600 shrink-0"
                        : "h-2 w-2 bg-red-500 shrink-0"
                  }
                />
                <span className="text-sm">{nas.name}</span>
                <span className="text-xs text-zinc-500">
                  {nas.address}:{nas.mcp_port}
                </span>
                {!nas.enabled && <span className="text-xs text-red-400 ml-auto">disabled</span>}
              </div>

              <div className="text-xs text-zinc-500">
                {!nas.has_token && <span className="text-amber-400">No token set · </span>}
                {nas.last_checked_at ? (
                  <>
                    {nas.last_check_ok ? "Checked " : "Last check failed "}
                    {when(nas.last_checked_at)}
                    {nas.last_check_detail && ` — ${nas.last_check_detail}`}
                  </>
                ) : (
                  "Never checked"
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-xs uppercase tracking-wide text-zinc-500">Where to go</h2>
        <div className="grid md:grid-cols-2 gap-3">
          {LINKS.map((link) => (
            <button
              key={link.page}
              onClick={() => onGo(link.page)}
              className="card text-left hover:border-amber-500/60 transition-colors"
            >
              <div className="text-sm text-zinc-100">{link.label}</div>
              <div className="text-xs text-zinc-500">{link.blurb}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
