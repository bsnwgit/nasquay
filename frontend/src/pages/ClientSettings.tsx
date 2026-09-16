import { useEffect, useState } from "react";
import { api, type Client, type Key, type Nas, type Target } from "../api";
import Help from "../components/Help";
import { when } from "../utils/format";
import { sshCopyCommand } from "../utils/sshCopy";

// Machines that mount a share, the keys used to reach them, and the mounts themselves.
//
// The NAS's own view is not the only one that matters: a share can be perfectly healthy on
// the NAS and simply not be mounted on the machine that needs it, and nothing on the NAS
// side would ever show that.
//
// Everything folds away. A page of open forms for things you configure once is a page you
// have to read past every time you come to look at what is already there.

function Row({
  title,
  detail,
  open,
  onToggle,
  children,
}: {
  title: string;
  detail?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="card space-y-3">
      <button className="w-full flex items-center gap-3 text-left" onClick={onToggle}>
        <span className="text-zinc-400 w-3">{open ? "▾" : "▸"}</span>
        <span className="text-sm">{title}</span>
        {detail && <span className="text-xs text-zinc-300">{detail}</span>}
      </button>
      {open && <div className="border-t border-zinc-600 pt-3 space-y-3">{children}</div>}
    </div>
  );
}

export default function ClientSettings() {
  const [clients, setClients] = useState<Client[]>([]);
  const [keys, setKeys] = useState<Key[]>([]);
  const [units, setUnits] = useState<Nas[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  // One machine at a time, chosen the same way a NAS is chosen elsewhere.
  const [selected, setSelected] = useState<number | null>(null);
  const [adding, setAdding] = useState({
    name: "", address: "", ssh_user: "", ssh_port: 22, key_name: "",
  });
  const [mount, setMount] = useState({ share: "", path: "" });
  // What is mounted on a client right now, per client, once asked for.
  const [present, setPresent] = useState<
    Record<number, { source: string; path: string; type: string; watched: boolean }[]>
  >({});
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    const [list, keyList, nasList, found] = await Promise.allSettled([
      api.clients.list(),
      api.keys.list(),
      api.nas.list(),
      api.monitoring.targets(),
    ]);
    if (list.status === "fulfilled") {
      setClients(list.value);
      if (list.value.length) setSelected((current) => current ?? list.value[0].id);
    }
    else setError(list.reason instanceof Error ? list.reason.message : "Could not load clients");
    if (keyList.status === "fulfilled") setKeys(keyList.value);
    if (nasList.status === "fulfilled") setUnits(nasList.value.filter((one) => one.enabled));
    if (found.status === "fulfilled") setTargets(found.value);
  };

  useEffect(() => {
    load();
  }, []);

  const act = async (what: () => Promise<unknown>, said: string) => {
    setError("");
    setNote("");
    try {
      await what();
      setNote(said);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
    }
  };

  const toggle = (key: string) => setOpen((current) => (current === key ? null : key));
  // Joined by id, so renaming a client cannot orphan its mounts.
  const mountsFor = (client: Client) =>
    targets.filter((one) => one.kind === "client_mount" && one.client_id === client.id);

  return (
    <div className="space-y-3">
      <Row title="Add client" open={open === "add"} onToggle={() => toggle("add")}>
        <div className="grid md:grid-cols-5 gap-3">
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Name</span>
            <input
              className="field"
              value={adding.name}
              onChange={(e) => setAdding({ ...adding, name: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Address</span>
            <input
              className="field"
              value={adding.address}
              onChange={(e) => setAdding({ ...adding, address: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">SSH user</span>
            <input
              className="field"
              value={adding.ssh_user}
              onChange={(e) => setAdding({ ...adding, ssh_user: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Port</span>
            <input
              className="field"
              type="number"
              value={adding.ssh_port}
              onChange={(e) => setAdding({ ...adding, ssh_port: Number(e.target.value) })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Key</span>
            <select
              className="field"
              value={adding.key_name}
              onChange={(e) => setAdding({ ...adding, key_name: e.target.value })}
            >
              <option value="">the install's own</option>
              {keys.map((key) => (
                <option key={key.name} value={key.name}>
                  {key.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          className="btn-primary"
          disabled={!adding.name || !adding.address || !adding.ssh_user}
          onClick={() =>
            act(async () => {
              await api.clients.create(adding);
              setAdding({ name: "", address: "", ssh_user: "", ssh_port: 22, key_name: "" });
            }, "Client added")
          }
        >
          Add client
        </button>
      </Row>

      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Clients</h2>
        <Help>
          <p>A client is a machine that mounts a share — the machine whose users notice first when something is wrong.</p>
          <p>NASQuay reaches it over SSH and asks only two fixed questions: is this path mounted, and what does <code>df</code> say about it. There is no free-form command here, exactly as there is none for a NAS.</p>
          <p>Each mount becomes an ordinary monitoring target, read in the fast tier, so a dropped mount is noticed in minutes. Two rules depend on it: one for a mount that has vanished, one for a client whose view disagrees with the NAS's.</p>
          <p>A client needs NASQuay's public key in its own authorised keys. Keys are generated and copied under Settings → SSH keys.</p>
        </Help>
        {clients.map((one) => (
          <button
            key={one.id}
            onClick={() => setSelected(one.id)}
            className={
              one.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-600 text-zinc-200 hover:border-zinc-500"
            }
          >
            {one.name}
          </button>
        ))}
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      {clients
        .filter((client) => client.id === selected)
        .map((client) => {
        const shares = targets.filter((one) => one.kind === "share");
        return (
          <div key={client.id} className="card space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm">{client.name}</span>
              <span className="text-xs text-zinc-300">
                {client.ssh_user}@{client.address}
                {client.ssh_port !== 22 && `:${client.ssh_port}`}
              </span>
              <span className="text-xs text-zinc-300">
                {client.mounts} {client.mounts === 1 ? "mount" : "mounts"}
                {client.key_name ? ` · key ${client.key_name}` : " · the install's key"}
              </span>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={
                  client.last_check_ok === null
                    ? "h-2 w-2 bg-zinc-600 shrink-0"
                    : client.last_check_ok
                      ? "h-2 w-2 bg-emerald-400 shrink-0"
                      : "h-2 w-2 bg-red-500 shrink-0"
                }
              />
              <span className="text-xs text-zinc-300">
                {client.last_checked_at
                  ? `${when(client.last_checked_at)} — ${client.last_check_detail}`
                  : "never tested"}
              </span>
              <span className="flex gap-2 ml-auto">
                <button
                  className="btn"
                  onClick={() => {
                    const next = window.prompt(`Rename ${client.name} to:`, client.name);
                    if (!next || next === client.name) return;
                    act(
                      () => api.clients.update(client.id, { name: next }),
                      `Renamed to ${next}`,
                    );
                  }}
                  title="Rename this client and relabel its mounts"
                >
                  Rename
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    const key = keys.find((one) =>
                      client.key_name ? one.name === client.key_name : !one.managed,
                    );
                    if (!key) {
                      setError("That client's key could not be found on the host");
                      return;
                    }
                    navigator.clipboard?.writeText(
                      sshCopyCommand(key.public_path, client.ssh_user, client.address,
                                     client.ssh_port),
                    );
                    setNote("Command copied — run it on the NASQuay host");
                  }}
                  title="Copy the command that authorises NASQuay on this client"
                >
                  Copy install command
                </button>
                <button
                  className="btn"
                  onClick={() => act(() => api.clients.check(client.id), `Checked ${client.name}`)}
                >
                  Test
                </button>
                <button
                  className="btn-danger"
                  onClick={() =>
                    act(() => api.clients.remove(client.id), `Removed ${client.name}`)
                  }
                >
                  Remove
                </button>
              </span>
            </div>

            <div className="border border-zinc-600 bg-zinc-900/40 p-3 space-y-2">
              <div className="flex items-center gap-3">
                <span className="text-xs uppercase tracking-wide text-sky-400">
                  Present on {client.name}
                </span>
                <span className="text-xs text-zinc-300">what the machine has mounted now</span>
                <button
                  className="btn ml-auto"
                  onClick={() =>
                    act(async () => {
                      const answer = await api.clients.discoverMounts(client.id);
                      setPresent((current) => ({ ...current, [client.id]: answer.mounts }));
                    }, "Read the client's mount table")
                  }
                >
                  {present[client.id] ? "Refresh" : "Look"}
                </button>
              </div>

              {present[client.id]?.length === 0 && (
                <div className="text-xs text-zinc-300">
                  Nothing from the network is mounted on this machine — which, if you expected a
                  share here, is itself the answer.
                </div>
              )}

              {(present[client.id] ?? []).map((one) => (
                <div
                  key={one.path}
                  className="grid grid-cols-[1fr_5rem_1fr_6rem] items-center gap-3 text-xs
                             py-1 border-b border-zinc-600/60 last:border-0"
                >
                  <span className="text-zinc-200 truncate" title={one.path}>
                    {one.path}
                  </span>
                  <span className="text-zinc-300">{one.type}</span>
                  <span className="text-zinc-300 truncate" title={one.source}>
                    {one.source}
                  </span>
                  {one.watched ? (
                    <span className="text-emerald-400 text-right">watched</span>
                  ) : (
                    <button
                      className="btn"
                      onClick={() => {
                        // The share is usually the last part of what it was mounted from.
                        const guess = one.source.split(/[:/\\]/).filter(Boolean).pop() ?? "";
                        const match = targets.find(
                          (t) => t.kind === "share" && t.ref.toLowerCase() === guess.toLowerCase(),
                        );
                        setMount({
                          path: one.path,
                          share: match ? `${match.nas_id}:${match.ref}` : "",
                        });
                      }}
                    >
                      Use this
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="border border-amber-500/30 bg-zinc-900/40 p-3 space-y-2">
              <div className="flex items-center gap-3">
                <span className="text-xs uppercase tracking-wide text-amber-400">Watched</span>
                <span className="text-xs text-zinc-300">what NASQuay reads and rules on</span>
              </div>
              <div className="grid grid-cols-[1fr_1fr_6rem] gap-3 text-xs text-zinc-300
                              border-b border-zinc-600 pb-1">
                <span>Path on {client.name}</span>
                <span>Is</span>
                <span />
              </div>
              {mountsFor(client).map((one) => (
                <div
                  key={one.id}
                  className="grid grid-cols-[1fr_1fr_6rem] items-center gap-3 text-xs py-1
                             border-b border-zinc-600/60 last:border-0"
                >
                  <span className="text-zinc-200 truncate" title={one.ref}>
                    {one.ref}
                  </span>
                  <span className="text-zinc-300">
                    {units.find((n) => n.id === one.nas_id)?.name ?? "a NAS"} ·{" "}
                    {one.parent_ref || "share not recorded"}
                  </span>
                  <button
                    className="btn-danger"
                    title="Stop watching this mount. Its readings go with it."
                    onClick={() =>
                      act(
                        () => api.clients.removeMount(one.id),
                        `No longer watching ${one.ref}`,
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
              ))}
              {mountsFor(client).length === 0 && (
                <div className="text-xs text-zinc-300">Nothing here is being watched yet.</div>
              )}
            </div>

            <div className="border-t border-zinc-600 pt-3 space-y-2">
              <div className="text-xs uppercase tracking-wide text-zinc-300">Add a mount</div>
              <div className="grid md:grid-cols-3 gap-3">
                <label className="space-y-1">
                  <span className="text-xs text-zinc-300">Which share this path is</span>
                  <select
                    className="field"
                    value={mount.share}
                    onChange={(e) => setMount({ ...mount, share: e.target.value })}
                  >
                    <option value="">choose</option>
                    {shares.map((one) => (
                      <option key={one.id} value={`${one.nas_id}:${one.ref}`}>
                        {units.find((n) => n.id === one.nas_id)?.name} · {one.ref}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 md:col-span-2">
                  <span className="text-xs text-zinc-300">Path on {client.name}</span>
                  <input
                    className="field"
                    placeholder="/Volumes/Series-A"
                    value={mount.path}
                    onChange={(e) => setMount({ ...mount, path: e.target.value })}
                  />
                </label>
              </div>
              <button
                className="btn-primary"
                disabled={!mount.share || !mount.path}
                onClick={() =>
                  act(async () => {
                    const [nasId, share] = mount.share.split(":");
                    await api.clients.addMount({
                      client_id: client.id,
                      nas_id: Number(nasId),
                      share,
                      path: mount.path,
                    });
                    setMount({ share: "", path: "" });
                  }, "Mount added — switch it on under Watched")
                }
              >
                Add mount
              </button>
            </div>
          </div>
        );
      })}

      {clients.length === 0 && (
        <div className="card text-sm text-zinc-300">
          No client machines yet. Open Add client above.
        </div>
      )}
    </div>
  );
}
