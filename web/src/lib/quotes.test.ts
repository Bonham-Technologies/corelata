import { findQuote, quoteSpans } from "./quotes";

const UNIT = "Tarvos Port Authority, 3 July 2026. Terminal B entered full service on 12 May 2026.";

it("finds a quote whatever its case, spacing, quote marks and punctuation", () => {
  const span = findQuote(UNIT, "“terminal  B entered\nFULL service”");
  expect(span).not.toBeNull();
  expect(UNIT.slice(...span!)).toBe("Terminal B entered full service");
  expect(UNIT.slice(...findQuote(UNIT, "3 July, 2026")!)).toBe("3 July 2026");
});

it("finds nothing for words the unit does not hold as one run, or for no words", () => {
  expect(findQuote(UNIT, "will shut the oil terminal")).toBeNull();
  expect(findQuote(UNIT, "Terminal entered full service")).toBeNull();
  expect(findQuote(UNIT, "“ ”")).toBeNull();
  expect(findQuote("short", "a much longer quote")).toBeNull();
});

it("sorts the spans of several quotes and joins those that overlap", () => {
  expect(
    quoteSpans(UNIT, ["full service on 12 May", "Terminal B entered full", "Tarvos", "absent"]),
  ).toEqual([
    [0, 6],
    [36, 77],
  ]);
  expect(quoteSpans(UNIT, [])).toEqual([]);
});
