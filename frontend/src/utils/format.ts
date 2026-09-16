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

// QNAP and NASQuay both hand back ISO timestamps; nobody needs the T or the offset.
export const when = (value?: string | null) =>
  value ? value.replace("T", " ").slice(0, 19) : "";
