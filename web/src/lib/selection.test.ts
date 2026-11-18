import {
  decodeSelection,
  encodeSelection,
  SELECTION_PARAM,
  sourceToken,
  withAdded,
} from "./selection";

/** 500 ids shaped like the API's (uuid4). */
const IDS = Array.from({ length: 500 }, (_, i) => {
  const hex = (i * 2654435761 + 12345).toString(16).padStart(12, "0").slice(-12);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(0, 3)}-8${hex.slice(3, 6)}-${hex}`;
});

/** The query string the page would write, as the browser sends it. */
function query(chosen: ReadonlySet<string>): string {
  const params = new URLSearchParams({ project: "6c3a0a9e-1c0e-4c9b-9a51-0d1f0b6b7f10" });
  params.set(SELECTION_PARAM, encodeSelection(IDS, chosen));
  return `/new?${params.toString()}`;
}

function roundTrip(chosen: ReadonlySet<string>): Set<string> {
  const value = new URLSearchParams(query(chosen).split("?")[1]).get(SELECTION_PARAM)!;
  return decodeSelection(value, IDS);
}

it("stays under 2 kB for 500 sources, all, none, half or every other one chosen (CRL-54)", () => {
  const cases = [
    new Set(IDS),
    new Set<string>(),
    new Set(IDS.slice(0, 250)),
    new Set(IDS.slice(250)),
    new Set(IDS.filter((_, i) => i % 2 === 0)),
    new Set(IDS.slice(0, 251)),
  ];
  for (const chosen of cases) {
    expect(query(chosen).length).toBeLessThan(2048);
    expect(roundTrip(chosen)).toEqual(chosen);
  }
  // the ids themselves would not fit: 500 × 36 characters before any separator
  expect(IDS.join(",").length).toBeGreaterThan(8 * 1024);
});

it("writes the shorter list: the chosen ones, or the ones left out", () => {
  expect(encodeSelection(IDS, new Set(IDS))).toBe("x");
  expect(encodeSelection(IDS, new Set())).toBe("i");
  expect(encodeSelection(IDS, new Set([IDS[7]!]))).toBe(`i.${sourceToken(IDS[7]!)}`);
  expect(encodeSelection(IDS, new Set(IDS.slice(1)))).toBe(`x.${sourceToken(IDS[0]!)}`);
  expect(encodeSelection([], new Set())).toBe("i");
});

it("gives every one of 500 sources its own six-character URL-safe token", () => {
  const tokens = IDS.map(sourceToken);
  expect(new Set(tokens).size).toBe(IDS.length);
  for (const token of tokens) expect(token).toMatch(/^[A-Za-z0-9_-]{6}$/);
  expect(sourceToken(IDS[0]!)).toBe(sourceToken(IDS[0]!)); // stable
  expect(new URLSearchParams({ p: `x.${tokens.join(".")}` }).toString()).toBe(
    `p=x.${tokens.join(".")}`, // nothing in it is percent-encoded
  );
});

it("an x list keeps a source the project gained later chosen; an i list leaves it out", () => {
  const before = IDS.slice(0, 10);
  const later = [...before, IDS[10]!];
  expect(decodeSelection(encodeSelection(before, new Set(before.slice(1))), later)).toEqual(
    new Set(later.slice(1)),
  );
  expect(decodeSelection(encodeSelection(before, new Set([before[0]!])), later)).toEqual(
    new Set([before[0]!]),
  );
});

it("a value this page did not write chooses none", () => {
  expect(decodeSelection("", IDS)).toEqual(new Set());
  expect(decodeSelection("q.abcdef", IDS)).toEqual(new Set());
});

it("adds uploaded sources to an i list, and leaves an x list as it is", () => {
  const [a, b, c] = IDS as [string, string, string];
  const value = encodeSelection([a, b], new Set([a]));
  expect(decodeSelection(withAdded(value, [c]), [a, b, c])).toEqual(new Set([a, c]));
  expect(withAdded(withAdded(value, [c]), [c])).toBe(withAdded(value, [c])); // once each
  expect(withAdded("x", [c])).toBe("x");
  expect(withAdded("x.abcdef", [c])).toBe("x.abcdef");
  expect(decodeSelection(withAdded("junk", [c]), [a, b, c])).toEqual(new Set([c]));
});
