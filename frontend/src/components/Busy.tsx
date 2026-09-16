// Shown while NASQuay is waiting on a NAS. Large and bright on purpose: a NAS can take
// several seconds to answer, and a faint line of text reads as a page that has hung.
export default function Busy({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16">
      <div
        className="h-16 w-16 rounded-full border-4 border-zinc-700 border-t-amber-400 animate-spin"
        role="status"
        aria-label={label}
      />
      <div className="text-sm text-amber-400">{label}</div>
    </div>
  );
}
