import { useEffect, useState } from "react";
import { api, type Key } from "../api";
import Help from "../components/Help";
import { sshCopyCommand } from "../utils/sshCopy";

// The keys NASQuay connects with, for NAS units and client machines alike — which is why
// they live here rather than inside either one.
//
// Only public halves are ever shown. There is no endpoint that returns a private key, no
// way to upload one, and nothing in the application reads one: its path is handed to
// `ssh` and that is the whole of it.

export default function KeysSettings() {
  const [keys, setKeys] = useState<Key[]>([]);
  const [newKey, setNewKey] = useState({ name: "", comment: "nasquay" });
  // Folded away: a key is generated once and then lived with.
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.keys
      .list()
      .then(setKeys)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load keys"));

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

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">SSH keys</h2>
        <Help>
          <p>The keys NASQuay uses to reach a NAS over SSH, and to reach the client machines that mount its shares.</p>
          <p>Generate one here, then copy its <span className="text-zinc-200">public</span> half into that machine's authorised keys. The private half never leaves this host: no page shows it, no endpoint returns it, and nothing in the application reads it — its path is passed to <code>ssh</code> and that is all.</p>
          <p>Generated keys have no passphrase, deliberately. NASQuay connects unattended and nothing can type one, so a passphrase would mean a key that simply does not work. The protection is the file mode and the fact that it stays on the host.</p>
          <p>A key still used by a client cannot be deleted.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

        <div className="card space-y-3">
        <button
          className="w-full flex items-center gap-3 text-left"
          onClick={() => setAdding((was) => !was)}
        >
          <span className="text-zinc-300 w-3">{adding ? "▾" : "▸"}</span>
          <span className="text-sm">Add key</span>
          <span className="text-xs text-zinc-300">
            generate a new one on this host and copy its public half to a machine
          </span>
        </button>
        {adding && (
          <div className="border-t border-zinc-600 pt-3">
        <div className="flex items-end gap-3 flex-wrap">
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Name</span>
            <input
              className="field w-48"
              value={newKey.name}
              onChange={(e) => setNewKey({ ...newKey, name: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-300">Comment</span>
            <input
              className="field w-48"
              value={newKey.comment}
              onChange={(e) => setNewKey({ ...newKey, comment: e.target.value })}
            />
          </label>
          <button
            className="btn-primary"
            disabled={!newKey.name}
            onClick={() =>
              act(async () => {
                await api.keys.create(newKey);
                setNewKey({ name: "", comment: "nasquay" });
              }, "Key generated — copy its public half to the client")
            }
          >
            Generate key
          </button>
        </div>
          </div>
        )}
      </div>

      {keys.map((key) => (
          <div key={key.name} className="card space-y-2">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm">{key.name}</span>
              <span className="text-xs text-zinc-300">{key.fingerprint}</span>
              {!key.managed && (
                <span className="text-xs text-zinc-300">the install's own</span>
              )}
              {key.in_use > 0 && (
                <span className="text-xs text-zinc-300">
                  used by {key.in_use} {key.in_use === 1 ? "client" : "clients"}
                </span>
              )}
              <span className="flex gap-2 ml-auto">
                <button
                  className="btn"
                  disabled={!key.managed}
                  title={
                    key.managed
                      ? "Rename this key and repoint every client that uses it"
                      : "The install's own key is named by the configuration"
                  }
                  onClick={() => {
                    const next = window.prompt(`Rename ${key.name} to:`, key.name);
                    if (!next || next === key.name) return;
                    act(
                      () => api.keys.rename(key.name, next),
                      `Renamed to ${next}${key.in_use ? " — its clients were repointed" : ""}`,
                    );
                  }}
                >
                  Rename
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    navigator.clipboard?.writeText(sshCopyCommand(key.public_path));
                    setNote("Command copied — edit USER@HOST and run it on the NASQuay host");
                  }}
                  title="Copy the command that puts this key on a remote machine"
                >
                  Copy install command
                </button>
                <button
                  className="btn"
                  onClick={() => navigator.clipboard?.writeText(key.public)}
                >
                  Copy public key
                </button>
                <button
                  className="btn-danger"
                  disabled={key.in_use > 0 || !key.managed}
                  title={
                    !key.managed
                      ? "The install's own key is not removed from here"
                      : key.in_use > 0
                        ? "A key in use by a client cannot be deleted"
                        : "Delete this key"
                  }
                  onClick={() => act(() => api.keys.remove(key.name), `Deleted ${key.name}`)}
                >
                  Delete
                </button>
              </span>
            </div>
            <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-all bg-zinc-900 p-2">
              {key.public}
            </pre>
          </div>
        ))}
        {keys.length === 0 && (
          <div className="text-xs text-zinc-300">
            No keys are managed here yet. The install's own key is still used by default.
          </div>
        )}

    </div>
  );
}
