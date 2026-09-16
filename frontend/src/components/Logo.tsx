// NASQuay's mark. A quay is where things are berthed and handed over, so: a gold berth —
// square-cornered like everything else in this interface — with three stacked bars inside
// it for the storage behind, and a tail cutting the corner to make the Q.
//
// Two colours only, both from the palette already in use: amber for the app's own chrome,
// sky for anything read off a NAS.

export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" role="img" aria-label="NASQuay" className={className}>
      <rect
        x="4.5"
        y="4.5"
        width="23"
        height="23"
        fill="none"
        strokeWidth="3"
        className="stroke-amber-500"
      />
      <path d="M21 21 L29.5 29.5" strokeWidth="3" className="stroke-amber-500" />
      <g className="fill-sky-400">
        <rect x="10" y="10.4" width="12" height="2.6" opacity="0.5" />
        <rect x="10" y="14.7" width="12" height="2.6" />
        <rect x="10" y="19" width="12" height="2.6" opacity="0.5" />
      </g>
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`font-semibold tracking-wide ${className}`}>
      NAS<span className="text-amber-400">Quay</span>
    </span>
  );
}
