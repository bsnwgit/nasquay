import { useEffect, useState } from "react";
import { api, type AuditRecord } from "../api";
import Help from "../components/Help";

export default function Audit() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [decision, setDecision] = useState("");
  const [actionId, setActionId] = useState("");
  const [error, setError] = useState("");

  const load = async (before: number | null = null) => {
    setError("");
    try {
      const page = await api.audit({
        limit: 100,
        before_id: before,
        decision: decision || undefined,
        action_id: actionId || undefined,
      });
      setRecords(before ? [...records, ...page.records] : page.records);
      setNextBefore(page.next_before_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the audit log");
    }
  };

  useEffect(() => {
    load(null);
  }, [decision]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Audit log</h1>
        <Help>
          <p>Every action NASQuay has taken or refused, whoever asked for it — a page, a scheduled routine or an outside tool. There is no path to a NAS that avoids this record.</p>
          <p>A refusal is recorded as fully as a success, including why it was refused, so an attempt that should not have happened leaves a trace.</p>
        </Help>
        <select className="field w-40" value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="">every decision</option>
          <option value="allowed">allowed</option>
          <option value="denied">denied</option>
        </select>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            load(null);
          }}
          className="flex gap-2"
        >
          <input className="field w-56" placeholder="action, e.g. users.create" value={actionId}
                 onChange={(e) => setActionId(e.target.value)} />
          <button className="btn">Filter</button>
        </form>
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="th">When</th>
            <th className="th">Who</th>
            <th className="th">Action</th>
            <th className="th">Target</th>
            <th className="th">Result</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td className="td text-zinc-300 whitespace-nowrap">{record.at.replace("T", " ").slice(0, 19)}</td>
              <td className="td">
                {record.actor_name}
                <div className="text-xs text-zinc-300">
                  {record.actor_kind} · {record.via}
                  {record.client_ip ? ` · ${record.client_ip}` : ""}
                </div>
              </td>
              <td className="td font-mono text-xs">{record.action_id}</td>
              <td className="td text-zinc-300">{record.target}</td>
              <td className="td">
                <span className={record.decision === "denied" ? "text-red-400" : "text-zinc-200"}>
                  {record.decision}
                  {record.outcome ? ` · ${record.outcome}` : ""}
                </span>
                <div className="text-xs text-zinc-300">{record.reason || record.detail}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {nextBefore && (
        <button className="btn" onClick={() => load(nextBefore)}>
          Load more
        </button>
      )}
    </div>
  );
}
