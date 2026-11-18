import { dateGroup, groupByDate, whenText } from "./dates";

const now = new Date("2026-10-16T15:00:00");
const ago = (hours: number) => new Date(now.getTime() - hours * 3600_000).toISOString();

it("groups by Today, This week and Earlier", () => {
  expect(dateGroup(ago(1), now)).toBe("Today");
  expect(dateGroup(ago(30), now)).toBe("This week");
  expect(dateGroup(ago(24 * 10), now)).toBe("Earlier");
  const groups = groupByDate([ago(200), ago(1), ago(2)], (iso) => iso, now);
  expect(groups.map((g) => [g.label, g.items.length])).toEqual([
    ["Today", 2],
    ["Earlier", 1],
  ]);
});

it("words how long ago something happened", () => {
  expect(whenText(ago(0), now, "en")).toBe("just now");
  expect(whenText(ago(0.05), now, "en")).toBe("3 minutes ago");
  expect(whenText(ago(5), now, "en")).toBe("5 hours ago");
  expect(whenText(ago(24 * 3), now, "en")).toBe("3 days ago");
  expect(whenText(ago(24 * 40), now, "en")).toBe(new Date(ago(24 * 40)).toLocaleDateString("en"));
});
