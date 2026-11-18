// Copied from Coglossa unchanged (spec §2.2).
export type DateGroup = "Today" | "This week" | "Earlier";
const DAY_MS = 24 * 3600_000;
const ORDER: DateGroup[] = ["Today", "This week", "Earlier"];

export function dateGroup(iso: string, now: Date = new Date()): DateGroup {
  const then = new Date(iso);
  if (then.toDateString() === now.toDateString()) return "Today";
  return now.getTime() - then.getTime() < 7 * DAY_MS ? "This week" : "Earlier";
}

export function groupByDate<T>(
  items: T[],
  dateOf: (item: T) => string,
  now: Date = new Date(),
): { label: DateGroup; items: T[] }[] {
  return ORDER.map((label) => ({
    label,
    items: items.filter((item) => dateGroup(dateOf(item), now) === label),
  })).filter((group) => group.items.length > 0);
}

/** "just now", "3 minutes ago", "5 hours ago", "3 days ago", or the date after a month. */
export function whenText(iso: string, now: Date = new Date(), locale?: string): string {
  const then = new Date(iso);
  const minutes = Math.round((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  const words = new Intl.RelativeTimeFormat(locale, { numeric: "always" });
  if (minutes < 60) return words.format(-minutes, "minute");
  if (minutes < 24 * 60) return words.format(-Math.round(minutes / 60), "hour");
  if (minutes < 30 * 24 * 60) return words.format(-Math.round(minutes / (24 * 60)), "day");
  return then.toLocaleDateString(locale);
}
