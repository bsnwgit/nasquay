import { useEffect, useMemo, useState } from "react";
import { api, type Action, type Role } from "../api";
import Help from "../components/Help";

export default function Roles() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [newRole, setNewRole] = useState({ name: "", description: "" });

  const load = async () => {
    setError("");
    try {
      const [roleList, actionList] = await Promise.all([api.roles.list(), api.roles.actions()]);
      setRoles(roleList);
      setActions(actionList);
      const current = roleList.find((r) => r.id === selected) ?? roleList[0];
      if (current) {
        setSelected(current.id);
        setChecked(new Set(current.permissions));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load roles");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const role = roles.find((r) => r.id === selected) ?? null;
  const readOnly = !!role?.is_admin;

  // A name that only differs in case is still taken: the database compares without case.
  const wanted = newRole.name.trim().toLowerCase();
  const nameTaken = wanted.length > 0 && roles.some((r) => r.name.toLowerCase() === wanted);

  const byCategory = useMemo(() => {
    const groups = new Map<string, Action[]>();
    for (const action of actions) {
      const list = groups.get(action.category) ?? [];
      list.push(action);
      groups.set(action.category, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [actions]);

  const run = async (what: string, action: () => Promise<unknown>) => {
    setError("");
    setNote("");
    try {
      await action();
      setNote(what);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
    }
  };

  const toggle = (id: string) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Roles and permissions</h1>
        <Help>
          <p>Every action NASQuay can perform, switched on or off per role — the app's own actions and every tool its NAS units offer.</p>
          <p>A tool nobody has reviewed cannot be run by anyone, including an administrator, until it is classified.</p>
          <p>These switches are checked before anything is sent to a NAS, and the same check covers the web pages, scheduled routines and the API alike.</p>
        </Help>
        {note && <span className="text-sm text-amber-400">{note}</span>}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      <div className="grid gap-4 md:grid-cols-[20rem_1fr]">
        <div className="space-y-3">
          <div className="card space-y-2">
            <div className="text-xs uppercase tracking-wide text-zinc-300">
              Roles ({roles.length})
            </div>
            {roles.map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  setSelected(r.id);
                  setChecked(new Set(r.permissions));
                }}
                className={
                  r.id === selected
                    ? "w-full text-left px-2 py-1 border border-amber-500 text-amber-400"
                    : "w-full text-left px-2 py-1 border border-transparent hover:border-zinc-700"
                }
              >
                <div className="text-sm">
                  {r.name}
                  {r.is_builtin && <span className="ml-2 text-xs text-zinc-300">built-in</span>}
                </div>
                <div className="text-xs text-zinc-300">
                  {r.is_admin ? "every permission" : `${r.permissions.length} permissions`} ·{" "}
                  {r.user_count} {r.user_count === 1 ? "user" : "users"}
                </div>
              </button>
            ))}
          </div>

          <form
            className="card space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              run("Role created", async () => {
                const created = await api.roles.create({
                  name: newRole.name.trim(),
                  description: newRole.description,
                });
                setNewRole({ name: "", description: "" });
                setSelected(created.id);
                setChecked(new Set());
              });
            }}
          >
            <div className="text-xs uppercase tracking-wide text-zinc-300">New role</div>
            <input
              className="field"
              placeholder="name"
              value={newRole.name}
              onChange={(e) => setNewRole({ ...newRole, name: e.target.value })}
            />
            {nameTaken && (
              <div className="text-xs text-red-400">
                A role called {newRole.name.trim()} already exists — names ignore case. Choose it
                on the left to edit it.
              </div>
            )}
            <input
              className="field"
              placeholder="description"
              value={newRole.description}
              onChange={(e) => setNewRole({ ...newRole, description: e.target.value })}
            />
            <button className="btn-primary w-full" disabled={!newRole.name.trim() || nameTaken}>
              Create role
            </button>
          </form>
        </div>

        <div className="card space-y-4">
          {!role && <div className="text-sm text-zinc-300">Choose a role.</div>}

          {role && (
            <>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="text-sm">{role.name}</div>
                <div className="text-xs text-zinc-300">{role.description}</div>
                {readOnly ? (
                  <div className="text-xs text-zinc-300">
                    Built in. Holds every permission, including any added later, and cannot be
                    edited or deleted.
                  </div>
                ) : (
                  <div className="ml-auto flex gap-2">
                    <button
                      className="btn-primary"
                      onClick={() =>
                        run("Permissions saved", () => api.roles.setPermissions(role.id, [...checked]))
                      }
                    >
                      Save permissions
                    </button>
                    <button
                      className="btn-danger"
                      onClick={() => {
                        if (window.confirm(`Delete the role ${role.name}?`))
                          run("Role deleted", () => api.roles.remove(role.id));
                      }}
                    >
                      Delete role
                    </button>
                  </div>
                )}
              </div>

              {byCategory.map(([category, list]) => (
                <div key={category} className="space-y-1">
                  <div className="text-xs uppercase tracking-wide text-zinc-300">{category}</div>
                  {list.map((action) => (
                    <label
                      key={action.id}
                      className={
                        readOnly
                          ? "flex items-start gap-2 text-sm py-1 opacity-60"
                          : "flex items-start gap-2 text-sm py-1"
                      }
                    >
                      <input
                        type="checkbox"
                        className="mt-1 accent-amber-500"
                        checked={readOnly || checked.has(action.id)}
                        disabled={readOnly}
                        onChange={() => toggle(action.id)}
                      />
                      <span>
                        <span className="font-mono text-xs text-zinc-200">{action.id}</span>
                        <span
                          className={
                            action.classification === "destructive"
                              ? "ml-2 text-xs text-red-400"
                              : action.classification === "write"
                                ? "ml-2 text-xs text-amber-400"
                                : "ml-2 text-xs text-zinc-300"
                          }
                        >
                          {action.classification}
                        </span>
                        <div className="text-xs text-zinc-300">{action.description}</div>
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
