import { useEffect, useState } from "react";
import { api, type Nas } from "../api";
import Busy from "../components/Busy";
import { bytes, when } from "../utils/format";
import Help from "../components/Help";

// Browsing a NAS through list_files. Paths here are File Station's, not the shell's: the
// root lists the shared folders, and a share is "/Series-B" rather than the real
// "/share/CACHEDEV3_DATA/Series-B", which the NAS refuses.
//
// Read-only. Nothing on this page copies, moves, renames or shares a file — those are
// separate actions, and the ones QNAP offers are classified destructive.

const PAGE = 50;

type Shared = {
  name?: string;
  path?: string;
  volume_id?: number;
  volume_name?: string;
};

type Item = {
  filename?: string;
  filesize?: number;
  type?: string;        // file | folder
  mtime?: string;
  owner?: string;
  group?: string;
  privilege?: string;
};

// What the two listings have in common, once normalised.
type Row = {
  name: string;
  folder: boolean;
  size?: number;
  mtime?: string;
  owner?: string;
  group?: string;
  privilege?: string;
  volume?: string;
};

const join = (path: string, name: string) => (path === "/" ? `/${name}` : `${path}/${name}`);

export default function Files() {
  const [units, setUnits] = useState<Nas[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [path, setPath] = useState("/");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
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
    let current = true;
    setBusy(`Reading ${path} on ${nasName}`);
    setError("");
    api
      .run(selected, "list_files", { path, limit: PAGE, offset })
      .then((result) => {
        if (!current) return;
        const data = (result.json_result ?? {}) as { data?: unknown[]; total?: number };
        const list = Array.isArray(data.data) ? data.data : [];
        setTotal(data.total ?? list.length);
        setRows(
          path === "/"
            ? (list as Shared[]).map((share) => ({
                name: share.name ?? "",
                folder: true,
                volume: share.volume_name,
              }))
            : (list as Item[]).map((item) => ({
                name: item.filename ?? "",
                folder: item.type === "folder",
                size: item.filesize,
                mtime: item.mtime,
                owner: item.owner,
                group: item.group,
                privilege: item.privilege,
              })),
        );
      })
      .catch((err) => {
        if (!current) return;
        setRows([]);
        setTotal(0);
        setError(err instanceof Error ? err.message : "Could not read that folder");
      })
      .finally(() => current && setBusy(""));
    return () => {
      current = false;
    };
  }, [selected, path, offset, units]);

  const go = (next: string) => {
    setOffset(0);
    setPath(next);
  };

  const segments = path === "/" ? [] : path.slice(1).split("/");
  const shown = offset + rows.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-sm uppercase tracking-wide text-zinc-300">Files</h1>
        <Help>
          <p>Browsing a NAS as it sees itself. Paths here are the ones its file service uses — a share is <code>/Series-B</code>, not its place on disk.</p>
          <p>Read-only. Nothing on this page copies, moves, renames, deletes or creates a share link.</p>
          <p>Sizes and dates are as the NAS reports them for each entry; a folder's size is not its contents' total. For that, use a deep read in Monitoring.</p>
        </Help>
        {units.map((nas) => (
          <button
            key={nas.id}
            onClick={() => {
              setSelected(nas.id);
              go("/");
            }}
            className={
              nas.id === selected
                ? "px-3 py-1 text-sm border border-amber-500 text-amber-400"
                : "px-3 py-1 text-sm border border-zinc-700 text-zinc-200 hover:border-zinc-500"
            }
          >
            {nas.name}
          </button>
        ))}
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {units.length === 0 && <div className="card text-sm text-zinc-300">No enabled NAS units.</div>}

      {units.length > 0 && (
        <div className="flex items-center gap-1 text-sm flex-wrap">
          <button
            onClick={() => go("/")}
            className={path === "/" ? "text-amber-400" : "text-zinc-300 hover:text-zinc-100"}
          >
            {nasName}
          </button>
          {segments.map((segment, index) => {
            const upto = `/${segments.slice(0, index + 1).join("/")}`;
            const last = index === segments.length - 1;
            return (
              <span key={upto} className="flex items-center gap-1">
                <span className="text-zinc-300">/</span>
                <button
                  onClick={() => go(upto)}
                  className={last ? "text-amber-400" : "text-zinc-300 hover:text-zinc-100"}
                >
                  {segment}
                </button>
              </span>
            );
          })}
        </div>
      )}

      {busy && <Busy label={busy} />}

      {!busy && !error && units.length > 0 && (
        <div className="card p-0">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="th">Name</th>
                <th className="th">Size</th>
                <th className="th">Modified</th>
                <th className="th">Owner</th>
                <th className="th">Mode</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name} className="hover:bg-zinc-900/60">
                  <td className="td">
                    {row.folder ? (
                      <button
                        onClick={() => go(join(path, row.name))}
                        className="text-zinc-100 hover:text-amber-400 text-left"
                      >
                        <span className="text-zinc-300 mr-2">▸</span>
                        {row.name}
                      </button>
                    ) : (
                      <span className="text-zinc-200">
                        <span className="text-zinc-400 mr-2">·</span>
                        {row.name}
                      </span>
                    )}
                    {row.volume && <span className="text-xs text-zinc-300 ml-2">{row.volume}</span>}
                  </td>
                  <td className="td text-zinc-300 whitespace-nowrap">
                    {row.folder ? "" : bytes(row.size)}
                  </td>
                  <td className="td text-zinc-300 whitespace-nowrap">{when(row.mtime)}</td>
                  <td className="td text-zinc-300 whitespace-nowrap">
                    {row.owner}
                    {row.group && <span className="text-zinc-300"> / {row.group}</span>}
                  </td>
                  <td className="td text-zinc-300 whitespace-nowrap">{row.privilege}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td className="td text-zinc-300" colSpan={5}>
                    Nothing here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {!busy && !error && total > PAGE && (
        <div className="flex items-center gap-3 text-xs text-zinc-300">
          <button
            className="btn"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            Previous
          </button>
          <button
            className="btn"
            disabled={shown >= total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Next
          </button>
          <span>
            {offset + 1}–{shown} of {total}
          </span>
        </div>
      )}
    </div>
  );
}
