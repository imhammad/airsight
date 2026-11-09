/** "40 min ago", "3 h ago", "2 days ago": how old a reading is, in words. */
export function ago(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export const HOUR = 3_600_000;

/** The start of the hour a moment falls in, as epoch milliseconds. */
export function startOfHour(ms: number): number {
  return Math.floor(ms / HOUR) * HOUR;
}

// Every sensor is in the Bay Area, so its hours read in Pacific time wherever you are
const BAY_AREA_HOUR = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  timeZone: "America/Los_Angeles",
});

/** "6 AM": the hour of a moment in Bay Area time. */
export function bayAreaHour(ms: number): string {
  return BAY_AREA_HOUR.format(ms);
}
