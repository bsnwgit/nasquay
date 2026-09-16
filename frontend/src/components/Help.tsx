import { useEffect, useRef, useState } from "react";

// The help button every page carries: a question mark in a blue circle, next to the page's
// title. It opens a panel explaining what the page shows and where the figures come from.
//
// Blue on purpose — amber is this interface's accent for "active" and "attention", and help
// is neither. The circle is one of the few round things here, which is what makes it read as
// a button rather than as part of the page.

export default function Help({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const holder = useRef<HTMLSpanElement>(null);

  // Clicking anywhere else closes it, as a popover should.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (holder.current && !holder.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <span className="relative inline-flex" ref={holder}>
      <button
        type="button"
        aria-label="What this page shows"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className={
          "h-5 w-5 rounded-full text-xs font-semibold flex items-center justify-center " +
          (open
            ? "bg-sky-400 text-zinc-950"
            : "bg-sky-600 text-white hover:bg-sky-500")
        }
      >
        ?
      </button>

      {open && (
        <div
          className="absolute left-0 top-7 z-30 w-[32rem] max-w-[calc(100vw-2rem)] border
                     border-sky-900 bg-zinc-900 p-4 text-xs text-zinc-300 space-y-2 shadow-xl"
          role="dialog"
        >
          {children}
        </div>
      )}
    </span>
  );
}
