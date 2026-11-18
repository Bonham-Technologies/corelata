import {
  durationBetween,
  formatDateTime,
  formatDuration,
  formatInt,
  isTerminal,
  splitIds,
  STAGES,
} from "./format";

it("knows the terminal states and the stages in order", () => {
  expect(isTerminal("completed")).toBe(true);
  expect(isTerminal("drafting")).toBe(false);
  expect(STAGES).toEqual(["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]);
});

it("formats durations for people", () => {
  expect(formatDuration(420)).toBe("420 ms");
  expect(formatDuration(2500)).toBe("2.5 s");
  expect(formatDuration(42_000)).toBe("42 s");
  expect(formatDuration(125_000)).toBe("2 min 5 s");
  expect(durationBetween("2026-01-01T00:00:00Z", "2026-01-01T00:00:03Z")).toBe(3000);
  expect(durationBetween("2026-01-01T00:00:00Z", null)).toBeNull();
});

it("formats dates and integers for the reader's locale", () => {
  expect(formatDateTime("2026-10-13T10:00:00Z")).toBe(
    new Date("2026-10-13T10:00:00Z").toLocaleString(),
  );
  expect(formatInt(1234567)).toBe((1234567).toLocaleString());
});

it("splits claim id lists", () => {
  expect(splitIds("c1 c3")).toEqual(["c1", "c3"]);
  expect(splitIds("")).toEqual([]);
  expect(splitIds(null)).toEqual([]);
});
