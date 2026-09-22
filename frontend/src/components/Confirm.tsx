import { useState } from "react";

// A confirmation drawn as a dialog rather than the browser's own box: the browser's is
// unstyled, easy to dismiss without reading, and cannot say what the consequence is in
// more than one line.
export default function Confirm({
  title,
  danger,
  detail,
  confirmLabel,
  busyLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  danger: string;
  detail?: React.ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        className="card w-full max-w-md space-y-3 border border-red-400"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="text-sm text-zinc-100">{title}</div>
        <div className="text-sm text-red-400">{danger}</div>
        {detail && <div className="text-xs text-zinc-300">{detail}</div>}
        <div className="flex gap-2 justify-end">
          <button className="btn" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            className="btn-danger"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? (busyLabel ?? "Working…") : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
