// Formatting shared by the pages. Both of these were written out three times before this
// file existed, which is what it is here to stop.

export const bytes = (value?: number) => {
  if (!value && value !== 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
};

// How long something has been up, from a count of seconds.
export const duration = (seconds?: number) => {
  if (!seconds && seconds !== 0) return "";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

// The zone every NASQuay time is shown in, set once from /api/health. Held here rather
// than passed through every page, because a timestamp is formatted in a dozen places and
// one of them would have been missed.
let zone = "UTC";

export const setTimezone = (name: string) => {
  zone = name || "UTC";
};

export const timezone = () => zone;

// A time NASQuay itself recorded. Stored in UTC — SQLite's datetime('now') is UTC — and
// shown in the configured zone.
export const when = (value?: string | null) => {
  if (!value) return "";
  const text = value.includes("T") ? value : value.replace(" ", "T");
  // A stored time carries no offset, so it is stamped as UTC before conversion.
  const stamped = /[Z+]|-\d\d:\d\d$/.test(text) ? text : `${text}Z`;
  const moment = new Date(stamped);
  if (Number.isNaN(moment.getTime())) return value.replace("T", " ").slice(0, 19);
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    })
      .format(moment)
      .replace(",", "");
  } catch {
    return value.replace("T", " ").slice(0, 19);
  }
};

// A time a NAS reported. It is that NAS's own local clock, so it is shown exactly as
// given — converting it would claim a zone the NAS never stated.
export const asGiven = (value?: string | null) =>
  value ? value.replace("T", " ").slice(0, 19) : "";
