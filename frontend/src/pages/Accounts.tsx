import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { duration } from "../utils/format";
import Help from "../components/Help";

// The accounts held on a NAS — not NASQuay's own, which are under Settings. Three
// listings load together, each through /api/run, so a role allowed one and refused
// another still gets the part it may see.

type Account = { name?: string; uid?: number; enabled?: boolean; is_admin?: boolean };
type Group = { name?: string; id?: number; description?: string };

type SharePermission = {
  name?: string;
  effective_permission?: string;
  user_permission?: string;
  group_permission?: string;
};

type AccountDetail = {
  name?: string;
  email?: string;
  description?: string;
  groups?: string[];
  sharedfolder_settings?: SharePermission[];
};

type GroupDetail = {
  name?: string;
  gid?: number;
  users?: string[];
  sharedfolders?: { name?: string; permission?: string }[];
};

type Online = {
  user?: string;
  ip?: string;
  resource?: string;
  service?: number;
  computer?: string;
  clientApp?: string;
  date?: string;
  time?: string;
  survival?: number;
};

const tone = (permission?: string) => {
  if (permission === "Deny") return "text-red-400";
  if (permission === "RW") return "text-zinc-100";
  return "text-zinc-300";
};

export default function Accounts() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [online, setOnline] = useState<Online[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [openAccount, setOpenAccount] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [accountDetail, setAccountDetail] = useState<Record<string, AccountDetail | null>>({});
  const [groupDetail, setGroupDetail] = useState<Record<string, GroupDetail | null>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

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

  const nasName = units.find((n) => n.id === selected)?.name ?? "the NAS";

  useEffect(() => {
    if (selected === null) return;
    setBusy(`Reading accounts from ${nasName}`);
    setError("");
    setProblems([]);
    setOpenAccount(null);
    setOpenGroup(null);
    setAccountDetail({});
    setGroupDetail({});

    Promise.allSettled([
      api.run(selected, "list_users"),
      api.run(selected, "list_groups"),
      api.run(selected, "list_online_users"),
    ])
      .then(([users, groupList, sessions]) => {
        const failures: string[] = [];
        const why = (reason: unknown, what: string) =>
          `${what}: ${reason instanceof Error ? reason.message : "refused"}`;

        if (users.status === "fulfilled") {
          const data = (users.value.json_result ?? {}) as { data?: Account[] };
          setAccounts(data.data ?? []);
        } else {
          setAccounts([]);
          failures.push(why(users.reason, "users"));
        }

        if (groupList.status === "fulfilled") {
          const data = (groupList.value.json_result ?? {}) as { data?: Group[] };
          setGroups(data.data ?? []);
        } else {
          setGroups([]);
          failures.push(why(groupList.reason, "groups"));
        }

        if (sessions.status === "fulfilled") {
          const data = (sessions.value.json_result ?? {}) as { users?: Online[] };
          setOnline(data.users ?? []);
        } else {
          setOnline([]);
          failures.push(why(sessions.reason, "sessions"));
        }

        setProblems(failures);
      })
      .finally(() => setBusy(""));
  }, [selected, units]);

  const showAccount = async (name: string) => {
    if (openAccount === name) {
      setOpenAccount(null);
      return;
    }
    setOpenAccount(name);
    if (accountDetail[name] !== undefined || selected === null) return;
    try {
      const result = await api.run(selected, "get_user", { name });
      const data = (result.json_result ?? {}) as AccountDetail;
      setAccountDetail((current) => ({ ...current, [name]: data }));
    } catch (err) {
      setAccountDetail((current) => ({ ...current, [name]: null }));
      setError(err instanceof Error ? err.message : `Could not read ${name}`);
    }
  };

  const showGroup = async (name: string) => {
    if (openGroup === name) {
      setOpenGroup(null);
      return;
    }
    setOpenGroup(name);
    if (groupDetail[name] !== undefined || selected === null) return;
    try {
      const result = await api.run(selected, "get_group", { name });
      const data = (result.json_result ?? {}) as GroupDetail;
      setGroupDetail((current) => ({ ...current, [name]: data }));
    } catch (err) {
      setGroupDetail((current) => ({ ...current, [name]: null }));
      setError(err instanceof Error ? err.message : `Could not read ${name}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Accounts</h1>
        <Help>
          <p>The accounts held on the NAS itself — not NASQuay's own users, which live under Settings.</p>
          <p><span className="text-zinc-200">Connected now</span> is every open session. NFS carries no user name, so those rows show a dash: an NFS client is trusted by address, not by login.</p>
          <p>Opening a user shows their effective permission on every share, and whether it came from the user or from a group. Opening a group shows its members.</p>
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
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {problems.length > 0 && !busy && (
        <div className="card text-xs text-zinc-300">Not shown — {problems.join(" · ")}</div>
      )}

      {busy && <Busy label={busy} />}

      {!busy && units.length > 0 && (
        <>
          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Connected now</h2>
            <div className="card p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="th">User</th>
                    <th className="th">From</th>
                    <th className="th">Resource</th>
                    <th className="th">Since</th>
                    <th className="th">Connected</th>
                  </tr>
                </thead>
                <tbody>
                  {online.map((session, index) => (
                    <tr key={`${session.ip}-${session.resource}-${index}`}>
                      {/* NFS carries no user, and the NAS writes "---" rather than leaving it out. */}
                      <td className="td text-zinc-200">
                        {session.user && session.user !== "---" ? session.user : "—"}
                      </td>
                      <td className="td text-zinc-300 whitespace-nowrap">{session.ip}</td>
                      <td className="td text-zinc-300">{session.resource}</td>
                      <td className="td text-zinc-300 whitespace-nowrap">
                        {session.date} {session.time}
                      </td>
                      <td className="td text-zinc-300 whitespace-nowrap">
                        {duration(session.survival)}
                      </td>
                    </tr>
                  ))}
                  {online.length === 0 && (
                    <tr>
                      <td className="td text-zinc-300" colSpan={5}>
                        Nobody is connected.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">
              Users on {nasName}
            </h2>
            {accounts.map((account) => {
              const name = account.name ?? "";
              const expanded = openAccount === name;
              const detail = accountDetail[name];
              return (
                <div key={name} className="card space-y-3">
                  <button
                    className="w-full flex items-center gap-3 text-left"
                    onClick={() => showAccount(name)}
                  >
                    <span className="text-zinc-300 w-3">{expanded ? "▾" : "▸"}</span>
                    <span className="text-sm">{name}</span>
                    <span className="text-xs text-zinc-300">uid {account.uid}</span>
                    {account.is_admin && <span className="text-xs text-amber-400">administrator</span>}
                    {!account.enabled && <span className="text-xs text-red-400">disabled</span>}
                  </button>

                  {expanded && (
                    <div className="border-t border-zinc-600 pt-3 space-y-3">
                      {detail === undefined && (
                        <Busy label={`Reading ${name}'s access on ${nasName}`} />
                      )}

                      {detail && (
                        <>
                          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-300">
                            {detail.email && <span>{detail.email}</span>}
                            {detail.description && <span>{detail.description}</span>}
                            <span>groups {detail.groups?.join(", ") || "none"}</span>
                          </div>

                          <table className="w-full text-xs">
                            <thead>
                              <tr>
                                <th className="th">Share</th>
                                <th className="th">Effective</th>
                                <th className="th">Set on the user</th>
                                <th className="th">From a group</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(detail.sharedfolder_settings ?? []).map((row) => (
                                <tr key={row.name}>
                                  <td className="td text-zinc-200">{row.name}</td>
                                  <td className={`td ${tone(row.effective_permission)}`}>
                                    {row.effective_permission}
                                  </td>
                                  <td className="td text-zinc-300">{row.user_permission}</td>
                                  <td className="td text-zinc-300">{row.group_permission}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="space-y-2">
            <h2 className="text-xs uppercase tracking-wide text-zinc-300">Groups</h2>
            {groups.map((group) => {
              const name = group.name ?? "";
              const expanded = openGroup === name;
              const detail = groupDetail[name];
              return (
                <div key={name} className="card space-y-3">
                  <button
                    className="w-full flex items-center gap-3 text-left"
                    onClick={() => showGroup(name)}
                  >
                    <span className="text-zinc-300 w-3">{expanded ? "▾" : "▸"}</span>
                    <span className="text-sm">{name}</span>
                    <span className="text-xs text-zinc-300">gid {group.id}</span>
                    {group.description && (
                      <span className="text-xs text-zinc-300">{group.description}</span>
                    )}
                  </button>

                  {expanded && (
                    <div className="border-t border-zinc-600 pt-3 space-y-2">
                      {detail === undefined && <Busy label={`Reading ${name} on ${nasName}`} />}

                      {detail && (
                        <>
                          <div className="text-xs text-zinc-300">
                            members {detail.users?.join(", ") || "none"}
                          </div>
                          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                            {(detail.sharedfolders ?? []).map((share) => (
                              <span key={share.name} className="text-zinc-300">
                                {share.name}{" "}
                                <span className={tone(share.permission)}>{share.permission}</span>
                              </span>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

        </>
      )}
    </div>
  );
}
