import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { bytes } from "../utils/format";
import Help from "../components/Help";

// Shared folders on each NAS. Everything here goes through /api/run, so a role that is
// not allowed list_shared_folder simply gets a refusal rather than a blank page.

type Share = {
  name?: string;
  comment?: string;
  volumeID?: string;
  file_count?: number;
  dir_count?: number;
  hidden?: boolean;
  worm_type?: string;
};

type ShareList = {
  sharedfolders?: Share[];
  total?: number;
  has_more?: boolean;
  acl_enabled?: boolean;
  win_acl_enabled?: boolean;
};

// The shape QNAP actually returns (MCP Assistant 1.0.0.2356, QTS 5.2.x): `permissions` is
// an object about the folder, and the entries are the list nested inside it.
type Entry = {
  name?: string;
  principal?: string;      // user | group
  permission?: string;     // RW and NO seen on QTS 5.2.x; anything else is shown as-is
  editable?: boolean;
};

type Detail = {
  name?: string;
  comment?: string;
  volumeID?: string;
  capacity_bytes?: number;
  allocated_bytes?: number;
  freesize_bytes?: number;
  used_percent?: number;
  permissions?: {
    owner?: string;
    individual?: boolean;
    permissions?: Entry[];
  };
};

// A share is also an NFS export, and on QTS the two are configured apart from each other:
// the ACL above says nothing about who may mount it over NFS. From
// get_shared_folder_permission_details, whose `nfs` block is the export as QTS holds it.
type Nfs = {
  enabled?: boolean;
  permission?: string;        // rw | ro
  allowed_ip?: string;        // "*" means every host on the network
  squash_option?: string;
  anonymous_user?: string;
  anonymous_group?: string;
  secure?: boolean;
  sync?: boolean;
  auth_sys?: boolean;
  krb5?: boolean;
  krb5i?: boolean;
  krb5p?: boolean;
};

// Kept apart from the share's own detail: a role may be allowed one call and not the other,
// and a refusal on this one must not empty the rest of the panel.
type NfsState = { info?: Nfs; error?: string };

export default function Shares() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [shares, setShares] = useState<Share[]>([]);
  const [meta, setMeta] = useState<ShareList>({});
  const [open, setOpen] = useState<string | null>(null);
  // null means that share's read failed — the spinner stops, the error shows at the top,
  // and opening it again tries once more.
  const [details, setDetails] = useState<Record<string, Detail | null>>({});
  const [nfs, setNfs] = useState<Record<string, NfsState>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  // Shares an administrator has chosen not to list. Said out loud: a page that quietly
  // omits a share is indistinguishable from one that failed to read it.
  const [hiddenCount, setHiddenCount] = useState(0);

  useEffect(() => {
    api.nas
      .list()
      .then((list) => {
        const enabled = list.filter((n) => n.enabled);
        setUnits(enabled);
        if (enabled.length && selected === null) setSelected(enabled[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the NAS list"));
  }, []);

  useEffect(() => {
    if (selected === null) return;
    const name = units.find((n) => n.id === selected)?.name ?? "the NAS";
    setBusy(`Reading shared folders from ${name}`);
    setError("");
    setShares([]);
    setOpen(null);
    setDetails({});
    setNfs({});
    api
      .run(selected, "list_shared_folder", { detailed: true })
      .then((result) => {
        const data = (result.json_result ?? {}) as ShareList;
        setHiddenCount(result.hidden);
        setMeta(data);
        setShares(data.sharedfolders ?? []);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not read the shares"))
      .finally(() => setBusy(""));
  }, [selected, units]);

  const openShare = async (share: Share) => {
    const key = share.name ?? "";
    if (open === key) {
      setOpen(null);
      return;
    }
    setOpen(key);
    if (details[key] || selected === null) return;

    setError("");
    const said = (err: unknown, fallback: string) =>
      err instanceof Error ? err.message : fallback;

    const [folder, exported] = await Promise.allSettled([
      api.run(selected, "get_shared_folder", {
        folder_name: key,
        include_permissions: true,
        detailed: true,
      }),
      api.run(selected, "get_shared_folder_permission_details", { share_name: key }),
    ]);

    if (folder.status === "fulfilled") {
      setDetails((current) => ({ ...current, [key]: (folder.value.json_result ?? {}) as Detail }));
    } else {
      setDetails((current) => ({ ...current, [key]: null }));
      setError(said(folder.reason, "Could not read that share"));
    }

    if (exported.status === "fulfilled") {
      const data = (exported.value.json_result ?? {}) as { nfs?: Nfs };
      setNfs((current) => ({ ...current, [key]: { info: data.nfs ?? {} } }));
    } else {
      setNfs((current) => ({
        ...current,
        [key]: { error: said(exported.reason, "Could not read the NFS export") },
      }));
    }
  };

  const nasName = units.find((n) => n.id === selected)?.name ?? "the NAS";

  const access = (entry: Entry) => {
    if (entry.permission === "RW") return "read and write";
    if (entry.permission === "NO") return "no access";
    return entry.permission || "unknown";
  };

  const auth = (info: Nfs) => {
    const on = [
      info.auth_sys && "AUTH_SYS",
      info.krb5 && "krb5",
      info.krb5i && "krb5i",
      info.krb5p && "krb5p",
    ].filter(Boolean);
    return on.length ? on.join(" + ") : "none";
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Shares</h1>
        <Help>
          <p>Every shared folder on the selected NAS. Opening one shows who may reach it and how.</p>
          <p><span className="text-zinc-200">Permissions</span> are the NAS's access list: each user or group, and whether the permission was set on them directly or inherited from a group.</p>
          <p><span className="text-zinc-200">NFS export</span> is configured separately from those permissions and does not follow them. An export open to every host is highlighted, because file permissions will not save you there.</p>
          <p>File and folder counts are the NAS's own cached figures and can be hours stale — Monitoring takes live counts.</p>
        </Help>
        {units.map((nas) => (
          <button
            key={nas.id}
            onClick={() => setSelected(nas.id)}
            className={
              nas.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-600 text-zinc-200 hover:border-zinc-500"
            }
          >
            {nas.name}
          </button>
        ))}
        {meta.total !== undefined && !busy && (
          <span className="text-xs text-zinc-300">
            {meta.total} shares
            {meta.acl_enabled ? " · ACLs on" : ""}
            {meta.has_more ? " · list truncated by the NAS" : ""}
            {hiddenCount > 0 ? ` · ${hiddenCount} hidden by your settings` : ""}
          </span>
        )}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {busy && <Busy label={busy} />}

      {!busy && shares.map((share) => {
        const key = share.name ?? "";
        const expanded = open === key;
        const detail = details[key];
        const entries = detail?.permissions?.permissions;
        const exported = nfs[key];
        return (
          <div key={key} className="card space-y-3">
            <button
              className="w-full flex items-center gap-3 text-left"
              onClick={() => openShare(share)}
            >
              <span className="text-zinc-300 w-3">{expanded ? "▾" : "▸"}</span>
              <span className="text-sm">{share.name}</span>
              {share.comment && <span className="text-xs text-zinc-300">{share.comment}</span>}
              <span className="text-xs text-zinc-300">
                volume {share.volumeID ?? "?"}
                {share.file_count !== undefined && ` · ${share.file_count} files`}
                {share.dir_count !== undefined && ` · ${share.dir_count} folders`}
              </span>
              {share.hidden && <span className="text-xs text-zinc-300">hidden</span>}
              {share.worm_type && share.worm_type !== "disabled" && (
                <span className="text-xs text-amber-400">WORM {share.worm_type}</span>
              )}
            </button>

            {expanded && (
              <div className="border-t border-zinc-600 pt-3 space-y-3">
                <div className="text-xs text-zinc-300">
                  File and folder counts come from the NAS's own cached figures, which lag
                  behind what is really there.
                </div>

                {detail === undefined && (
                  <Busy label={`Reading ${key}'s permissions and NFS export from ${nasName}`} />
                )}

                {detail && (
                  <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-300">
                    {/* These are the volume's figures, not the share's: QNAP returns no
                        per-share size here, and used + free comes to the volume capacity. */}
                    <span>
                      volume {bytes(detail.allocated_bytes)} used, {bytes(detail.freesize_bytes)} free
                      of {bytes(detail.capacity_bytes)}
                      {detail.used_percent !== undefined && ` · ${detail.used_percent}% full`}
                    </span>
                    {detail.permissions?.owner && <span>owner {detail.permissions.owner}</span>}
                    {detail.permissions?.individual && <span className="text-amber-400">individual permissions</span>}
                  </div>
                )}

                {entries && entries.length === 0 && (
                  <div className="text-sm text-zinc-300">
                    The NAS returned no permission entries for this share.
                  </div>
                )}

                {entries && entries.length > 0 && (
                  <div className="grid md:grid-cols-2 gap-x-12">
                    {entries.map((entry, index) => (
                      <div
                        key={`${entry.name ?? index}-${index}`}
                        className="flex items-center gap-2 text-xs py-0.5 border-b border-zinc-600/40 last:border-0"
                      >
                        <span className="text-zinc-200 flex-1 truncate">{entry.name ?? "unknown"}</span>
                        <span className="text-zinc-300">{entry.principal ?? ""}</span>
                        <span
                          className={
                            entry.permission === "NO" ? "text-red-400" : "text-zinc-300"
                          }
                        >
                          {access(entry)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {exported && (
                  <div className="border-t border-zinc-600/60 pt-2 text-xs">
                    {exported.error ? (
                      <span className="text-zinc-300">
                        NFS export not read — {exported.error}
                      </span>
                    ) : exported.info?.enabled ? (
                      <div className="flex flex-wrap gap-x-6 gap-y-1 text-zinc-300">
                        <span className="text-zinc-200">
                          NFS {(exported.info.permission ?? "").toUpperCase() || "—"}
                        </span>
                        <span
                          className={
                            // Exported to every host, writable: worth seeing at a glance.
                            exported.info.allowed_ip === "*" && exported.info.permission === "rw"
                              ? "text-amber-400"
                              : undefined
                          }
                        >
                          clients {exported.info.allowed_ip || "—"}
                        </span>
                        <span>
                          {exported.info.squash_option || "no squash"}
                          {exported.info.anonymous_user &&
                            ` as ${exported.info.anonymous_user} / ${exported.info.anonymous_group}`}
                        </span>
                        <span>sync {exported.info.sync ? "on" : "off"}</span>
                        <span>secure {exported.info.secure ? "on" : "off"}</span>
                        <span>auth {auth(exported.info)}</span>
                      </div>
                    ) : (
                      <span className="text-zinc-300">NFS export off</span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {!busy && !error && units.length > 0 && shares.length === 0 && (
        <div className="card text-sm text-zinc-300">No shared folders reported.</div>
      )}
    </div>
  );
}
