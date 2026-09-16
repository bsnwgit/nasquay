import { useEffect, useState } from "react";
import { api, type Run } from "../api";
import { when } from "../utils/format";

// Whatever is going wrong, said out loud — and nothing that has stopped going wrong.
//
// A scheduled run fails while nobody is watching: its problems go into the run record and
// stay there. A monitor whose own failures are silent is the thing it was built to prevent.
// But a panel that keeps showing this morning's fault after it was fixed is just as bad, so
// only failures since the last run that worked are shown. The rest are counted, and can be
// unfolded.

type Kind = "client" | "nas";

// The collector marks a client's problems by starting them with "client ". Everything else
// came from the NAS side.
const isClient = (problem: string) => problem.trimStart().startsWith("client ");

const partsOf = (detail: string, only?: Kind) => {
  const parts = detail.split(" · ").filter(Boolean);
  if (!only) return parts;
  return parts.filter((one) => (only === "client" ? isClient(one) : !isClient(one)));
};

// Trouble is current if it happened after the most recent run of its tier that succeeded.
const current = (runs: Run[]) => {
  const settled: Record<string, string> = {};
  for (const run of runs) {
    if (run.status === "ok" && !settled[run.tier]) settled[run.tier] = run.started_at;
  }
  return runs.filter(
    (run) =>
      (run.status === "failed" || run.status === "partial") &&
      (!settled[run.tier] || run.started_at > settled[run.tier]),
  );
};

export default function Trouble({
  limit = 20,
  runs: given,
  only,
}: {
  limit?: number;
  runs?: Run[];
  only?: Kind;
}) {
  const [fetched, setFetched] = useState<Run[]>([]);
  const [showPast, setShowPast] = useState(false);

  useEffect(() => {
    if (given) return;
    api.monitoring
      .runs(limit)
      .then(setFetched)
      // A role that may not read runs simply does not see this panel.
      .catch(() => setFetched([]));
  }, [limit, given]);

  const runs = given ?? fetched;
  const live = current(runs).filter((run) => partsOf(run.detail, only).length > 0 || !run.detail);
  const past = runs
    .filter((run) => run.status !== "ok" && !live.includes(run))
    .filter((run) => partsOf(run.detail, only).length > 0 || !run.detail);

  const show = showPast ? [...live, ...past] : live;

  if (show.length === 0 && past.length === 0) return null;

  // The same failure every five minutes is one problem, not twelve.
  const seen = new Set<string>();
  const distinct = show.filter((one) => {
    const key = `${one.status}:${partsOf(one.detail, only).join(" · ")}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="space-y-2">
      {distinct.map((run) => (
        <div
          key={run.id}
          className={
            "card border-l-2 " +
            (run.status === "failed" ? "border-l-red-500" : "border-l-amber-500") +
            (live.includes(run) ? "" : " opacity-60")
          }
        >
          <div className="flex items-center gap-3 flex-wrap">
            <span
              className={
                run.status === "failed" ? "text-sm text-red-400" : "text-sm text-amber-400"
              }
            >
              {run.tier} collection {run.status}
            </span>
            <span className="text-xs text-zinc-300">{when(run.started_at)}</span>
            <span className="text-xs text-zinc-300">
              {run.readings} {run.readings === 1 ? "reading" : "readings"}
            </span>
            {!live.includes(run) && (
              <span className="text-xs text-zinc-300">since resolved</span>
            )}
          </div>
          {run.detail && (
            <div className="text-xs text-zinc-200">
              {partsOf(run.detail, only).join(" · ") || run.detail}
            </div>
          )}
        </div>
      ))}

      {past.length > 0 && (
        <button
          className="text-xs text-zinc-300 hover:text-zinc-100"
          onClick={() => setShowPast((was) => !was)}
        >
          {showPast
            ? "hide earlier problems"
            : `${past.length} earlier problem${past.length === 1 ? "" : "s"}, since resolved`}
        </button>
      )}
    </div>
  );
}

// Which runs count as trouble now. Exported so a page's summary says the same thing as the
// panel underneath it.
export const troubled = (runs: Run[]) => current(runs);
