/**
 * The embedded assistant, mounted by NASQuay rather than by resonance's loader.
 *
 * The loader expects the code endpoint to authenticate by cookie. NASQuay's session is
 * an access token held in memory and a refresh cookie scoped to /api/auth, which is
 * exactly the case the embed contract says writes its own mount. So this writes the four
 * things the loader would have written: the mount, the renewal, the origin check, and
 * `allow="microphone"` — without which the microphone is refused inside the frame
 * whatever the key grants, and the assistant reads as broken.
 *
 * Mounted once, inside the signed-in layout, never per page: every mount costs a code,
 * and a remount throws away the conversation that was running.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, assistantCall, type ResonanceConfig } from "../api";

// A minute of headroom before the session lapses, so a failed renewal has time to be
// retried — and unlike the loader, this one retries.
const RENEW_MARGIN_SECONDS = 60;
const MIN_RENEW_SECONDS = 30;
const RENEW_RETRIES = 3;
const RENEW_RETRY_MS = 5000;

// The operations the assistant may ask for, resolved from NASQuay's own spec rather than
// hard-coded here: the grant file names operation ids, and an id is the only name stable
// enough to grant against.
const SPEC_PATH = "/api/resonance/openapi.json";

type Operation = { path: string; query: string[] };

async function readSpec(): Promise<Record<string, Operation>> {
  const operations: Record<string, Operation> = {};
  try {
    const response = await fetch(SPEC_PATH, { cache: "no-store" });
    if (!response.ok) return operations;
    const spec = (await response.json()) as {
      paths?: Record<string, Record<string, { operationId?: string; parameters?: { name: string; in: string }[] }>>;
    };
    for (const [path, methods] of Object.entries(spec.paths ?? {})) {
      // GET only. This surface has nothing else, and a frame asking for anything else is
      // asking for something it was never granted.
      const get = methods.get;
      if (!get?.operationId) continue;
      operations[get.operationId] = {
        path,
        query: (get.parameters ?? []).filter((p) => p.in === "query").map((p) => p.name),
      };
    }
  } catch {
    // No spec, no operations: the assistant can still talk.
  }
  return operations;
}

export default function ResonanceMount() {
  const [config, setConfig] = useState<ResonanceConfig | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const holder = useRef<HTMLDivElement | null>(null);
  const frame = useRef<HTMLIFrameElement | null>(null);
  const timer = useRef<number | null>(null);
  const operations = useRef<Record<string, Operation>>({});

  useEffect(() => {
    // A role that may not open the assistant still loads this: the panel simply never
    // appears, because the code it would need is refused.
    api.resonance.config().then(setConfig).catch(() => setConfig(null));
    readSpec().then((found) => {
      operations.current = found;
    });
  }, []);

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const renew = useCallback(async (attempt = 0) => {
    try {
      const session = await api.resonance.code();
      frame.current?.contentWindow?.postMessage(
        { rsn: 1, kind: "renew", code: session.code },
        session.base_url,
      );
    } catch {
      if (attempt < RENEW_RETRIES) {
        timer.current = window.setTimeout(() => renew(attempt + 1), RENEW_RETRY_MS * (attempt + 1));
      }
      // Past that, the session lapses on its own. Destroying a live conversation to
      // pre-empt a lapse would be the worse failure.
    }
  }, []);

  // Only our frame, only resonance's origin. The page may embed other things.
  useEffect(() => {
    if (!config?.enabled) return;
    const origin = config.base_url.replace(/\/+$/, "");

    const onMessage = async (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return;
      if (event.origin !== origin) return;
      const message = event.data as {
        rsn?: number;
        kind?: string;
        expires_in?: number;
        id?: number;
        op?: string;
        params?: Record<string, unknown>;
      };
      if (!message || message.rsn !== 1) return;

      if (message.kind === "ready" || message.kind === "renewed") {
        clearTimer();
        const seconds = Math.max(MIN_RENEW_SECONDS, (message.expires_in ?? 0) - RENEW_MARGIN_SECONDS);
        timer.current = window.setTimeout(() => renew(), seconds * 1000);
        return;
      }

      // An operation the assistant wants performed. NASQuay performs it, as the person
      // signed in here, and posts back what came out — the frame never gets a token, and
      // never reaches anything the grant file does not name.
      if (message.kind === "call" && message.op) {
        const reply = (status: number, body: unknown) =>
          frame.current?.contentWindow?.postMessage(
            { rsn: 1, kind: "result", id: message.id, status, body },
            origin,
          );

        const operation = operations.current[message.op];
        if (!operation) {
          reply(404, { error: `NASQuay has no operation called ${message.op}` });
          return;
        }
        const query = new URLSearchParams();
        for (const name of operation.query) {
          const value = message.params?.[name];
          if (value !== undefined && value !== null && value !== "") {
            query.set(name, String(value));
          }
        }
        try {
          const result = await assistantCall(
            operation.path + (query.toString() ? `?${query}` : ""),
          );
          reply(result.status, result.body);
        } catch (err) {
          reply(502, { error: err instanceof Error ? err.message : "The call failed" });
        }
      }
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [config, renew]);

  // Opening mounts the frame; closing takes it away, because a frame left in place keeps
  // its session and its renewal timer running behind a panel nobody is looking at.
  useEffect(() => {
    if (!open || !config?.enabled || !holder.current) return;
    let cancelled = false;
    setError("");

    api.resonance
      .code()
      .then((session) => {
        if (cancelled || !holder.current) return;
        const element = document.createElement("iframe");
        element.src = `${session.base_url.replace(/\/+$/, "")}${session.src || `/embed?c=${encodeURIComponent(session.code)}`}`;
        element.setAttribute("allow", "microphone");
        element.style.cssText = "width:100%;height:100%;border:0;display:block";
        holder.current.appendChild(element);
        frame.current = element;
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "The assistant did not open");
      });

    return () => {
      cancelled = true;
      clearTimer();
      frame.current?.remove();
      frame.current = null;
    };
  }, [open, config]);

  if (!config?.enabled) return null;

  const side = config.side === "left" ? "left-4" : "right-4";

  return (
    <>
      {open && (
        <div
          className={`fixed bottom-20 ${side} z-40 w-[380px] h-[520px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-7rem)] border border-zinc-600 bg-zinc-900 shadow-xl`}
        >
          <div className="flex items-center gap-2 border-b border-zinc-600 px-3 py-2">
            <span className="text-xs uppercase tracking-widest text-amber-400">{config.label}</span>
            {error && <span className="text-xs text-red-400 truncate">{error}</span>}
            <button
              className="ml-auto text-xs text-zinc-300 hover:text-zinc-100"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>
          <div ref={holder} className="h-[calc(100%-2.25rem)]" />
        </div>
      )}

      {/* A bubble, not a labelled button. `rounded-full` is the one radius the suite's
          theme keeps, and ice blue is its secondary channel — the assistant is not a
          system control, so it does not take the gold. */}
      <button
        onClick={() => setOpen((was) => !was)}
        title={open ? `Hide ${config.label}` : config.label}
        aria-label={open ? `Hide ${config.label}` : config.label}
        className={`fixed bottom-4 ${side} z-40 h-12 w-12 rounded-full flex items-center justify-center bg-sky-600 text-white shadow-lg hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-300`}
      >
        {open ? (
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor"
               strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 12a8 8 0 0 1-8 8H7l-4 3v-5.2A8 8 0 0 1 13 4a8 8 0 0 1 8 8z" />
          </svg>
        )}
      </button>
    </>
  );
}
