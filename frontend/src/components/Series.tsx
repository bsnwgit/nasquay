import { type Reading } from "../api";

// One metric over time, drawn as plain SVG. No charting library: this is a line, a band
// between the lowest and highest value seen, and the two end labels — everything else the
// table underneath says better.
//
// The y-axis deliberately does NOT start at zero. A volume that sits at 91% full all year
// would be a flat line against a zero axis, and the whole point here is to make a change
// of a few percent visible. The range is labelled so nobody reads the shape as absolute.

const WIDTH = 720;
const HEIGHT = 120;
const PAD = 8;

export default function Series({
  readings,
  format,
}: {
  readings: Reading[];
  format: (value: number) => string;
}) {
  // The API returns newest first; a chart reads oldest to newest.
  const points = [...readings]
    .filter((one) => one.value !== null)
    .reverse() as (Reading & { value: number })[];

  if (points.length < 2) {
    return (
      <div className="text-xs text-zinc-300">
        Only {points.length} reading so far — a line needs at least two. Read again later, or
        let the schedule build it up.
      </div>
    );
  }

  const values = points.map((one) => one.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;

  const x = (index: number) => PAD + (index / (points.length - 1)) * (WIDTH - PAD * 2);
  const y = (value: number) => HEIGHT - PAD - ((value - low) / span) * (HEIGHT - PAD * 2);

  const line = points.map((one, index) => `${x(index)},${y(one.value)}`).join(" ");
  const area = `${PAD},${HEIGHT - PAD} ${line} ${WIDTH - PAD},${HEIGHT - PAD}`;

  const first = points[0];
  const last = points[points.length - 1];
  const change = last.value - first.value;

  return (
    <div className="space-y-1">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-28"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${points.length} readings from ${first.taken_at} to ${last.taken_at}`}
      >
        <polygon points={area} className="fill-amber-500/10" />
        <polyline
          points={line}
          fill="none"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          className="stroke-amber-400"
        />
        {points.map((one, index) => (
          <circle
            key={`${one.taken_at}-${index}`}
            cx={x(index)}
            cy={y(one.value)}
            r="2"
            vectorEffect="non-scaling-stroke"
            className="fill-amber-300"
          >
            <title>{`${one.taken_at} — ${format(one.value)}`}</title>
          </circle>
        ))}
      </svg>

      <div className="flex flex-wrap gap-x-6 text-xs text-zinc-300">
        <span>
          {points.length} readings, {first.taken_at.slice(0, 16)} to {last.taken_at.slice(0, 16)}
        </span>
        <span>
          low {format(low)} · high {format(high)}
        </span>
        <span
          className={change < 0 ? "text-red-400" : change > 0 ? "text-emerald-400" : undefined}
        >
          {change === 0
            ? "no change across the range"
            : `${change < 0 ? "down" : "up"} ${format(Math.abs(change))} over the range`}
        </span>
      </div>
    </div>
  );
}
