import { useEffect, useState } from "react";
import { api, type Role, type User } from "../api";
import Help from "../components/Help";

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "", role_id: 0 });

  const load = async () => {
    setError("");
    try {
      const [userList, roleList] = await Promise.all([api.users.list(), api.roles.list()]);
      setUsers(userList);
      setRoles(roleList);
      if (!form.role_id && roleList.length) setForm((f) => ({ ...f, role_id: roleList[0].id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load users");
    }
  };

  useEffect(() => {
    load();
  }, []);

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

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Users</h1>
        <Help>
          <p>NASQuay's own accounts, which are separate from the accounts on any NAS.</p>
          <p>A user's role decides what they may do. The last remaining administrator cannot be disabled, demoted or deleted — by the interface or by the database.</p>
        </Help>
        <button className="btn" onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "Add user"}
        </button>
        {note && <span className="text-sm text-amber-400">{note}</span>}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {creating && (
        <form
          className="card grid gap-3 md:grid-cols-5"
          onSubmit={(e) => {
            e.preventDefault();
            run("User created", async () => {
              await api.users.create(form);
              setForm({ username: "", display_name: "", email: "", password: "", role_id: roles[0]?.id ?? 0 });
              setCreating(false);
            });
          }}
        >
          <input className="field" placeholder="username" value={form.username}
                 onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input className="field" placeholder="display name" value={form.display_name}
                 onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          <input className="field" placeholder="email" value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="field" type="password" placeholder="password (10+ characters)"
                 value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <div className="flex gap-2">
            <select className="field" value={form.role_id}
                    onChange={(e) => setForm({ ...form, role_id: Number(e.target.value) })}>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>{role.name}</option>
              ))}
            </select>
            <button className="btn-primary">Create</button>
          </div>
        </form>
      )}

      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="th">User</th>
            <th className="th">Role</th>
            <th className="th">Active</th>
            <th className="th">Last signed in</th>
            <th className="th"></th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td className="td">
                <div>{user.username}</div>
                <div className="text-xs text-zinc-300">
                  {user.display_name}
                  {user.display_name && user.email ? " · " : ""}
                  {user.email}
                </div>
              </td>
              <td className="td">
                <select
                  className="field w-40"
                  value={user.role_id}
                  onChange={(e) =>
                    run("Role changed", () => api.users.update(user.id, { role_id: Number(e.target.value) }))
                  }
                >
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>{role.name}</option>
                  ))}
                </select>
              </td>
              <td className="td">
                <button
                  className={user.is_active ? "btn-on" : "btn-off"}
                  onClick={() =>
                    run(user.is_active ? "User disabled" : "User enabled", () =>
                      api.users.update(user.id, { is_active: !user.is_active }),
                    )
                  }
                >
                  {user.is_active ? "Enabled" : "Disabled"}
                </button>
              </td>
              <td className="td text-zinc-300">{user.last_login ?? "never"}</td>
              <td className="td">
                <div className="flex gap-2 justify-end">
                  <button
                    className="btn"
                    onClick={() => {
                      const password = window.prompt(`New password for ${user.username}`);
                      if (password) run("Password set", () => api.users.resetPassword(user.id, password));
                    }}
                  >
                    Set password
                  </button>
                  <button
                    className="btn-danger"
                    onClick={() => {
                      if (window.confirm(`Delete ${user.username}? This cannot be undone.`))
                        run("User deleted", () => api.users.remove(user.id));
                    }}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
