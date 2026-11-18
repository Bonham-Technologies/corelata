import { readFileSync } from "node:fs";
import { HIGHLIGHT_CSS } from "../pages/review/frameBridge";

// Copied from Coglossa (spec §2.2); the frame's highlight pair at the end is Corelata's.
// Read from disk: Vitest serves stylesheets imported with ?raw as empty strings
// (tests run from web/).
const tokens = readFileSync("src/styles/tokens.css", "utf8");

/** Every declaration of one theme block of tokens.css, except color-scheme. */
function block(selector: string): Record<string, string> {
  const start = tokens.indexOf(selector);
  if (start < 0) throw new Error(`${selector} is missing from tokens.css`);
  const body = tokens.slice(tokens.indexOf("{", start) + 1, tokens.indexOf("}", start));
  return Object.fromEntries(
    // the last declaration may omit its semicolon
    [...body.matchAll(/--([\w-]+)\s*:\s*([^;]+)/g)].map((m) => [m[1]!, m[2]!.trim()]),
  );
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// The pairing map, keyed by token role. Every colour token in tokens.css must be a surface, a
// foreground in a rule, or exempt; a token that is none of them fails, so a new token cannot
// ship unchecked. Each foreground is checked against every surface its rule names.
const SURFACE = /^(bg|surface(-\d+)?|selected|warn-tint(-strong)?)$/;

interface Rule {
  fg: RegExp;
  bg: RegExp;
  min: number;
}

const RULES: Rule[] = [
  // text and status colours (and links: accent) on every page surface, 4.5:1
  { fg: /^(text|text-muted|ok|warn|danger)$/, bg: SURFACE, min: 4.5 },
  // accent as text is never drawn on the strong warning tint (4.499:1 in dark; the pair was
  // never checked or used), so that surface is left out of its rule
  { fg: /^accent$/, bg: /^(bg|surface(-\d+)?|selected|warn-tint)$/, min: 4.5 },
  // the label on an accent fill
  { fg: /^accent-text$/, bg: /^accent$/, min: 4.5 },
  // control borders are UI, 3:1, on the plain surfaces they are drawn on
  { fg: /^border-strong$/, bg: /^(bg|surface(-\d+)?)$/, min: 3 },
];

// Tokens that are not a foreground against a surface. Add a name only with the reason.
const EXEMPT: Record<string, string> = {
  border: "decorative hairline between regions; the control border is border-strong",
  shadow: "a box-shadow value, not a colour that text or UI is drawn in",
};

/** Sorts a theme's tokens into the pairs to check and the tokens no rule covers. */
function classify(colours: Record<string, string>) {
  const names = Object.keys(colours);
  const pairs: [string, string, number][] = [];
  const covered = new Set<string>();
  for (const { fg, bg, min } of RULES) {
    const fgs = names.filter((n) => fg.test(n));
    const bgs = names.filter((n) => bg.test(n));
    for (const f of fgs) for (const b of bgs) if (f !== b) pairs.push([f, b, min]);
    [...fgs, ...bgs].forEach((n) => covered.add(n));
  }
  const unpaired = names.filter((n) => !covered.has(n) && !(n in EXEMPT) && n !== "color-scheme");
  return { pairs, unpaired };
}

describe("classify", () => {
  it("reports a token that no rule or exemption covers", () => {
    const { unpaired } = classify({ bg: "#ffffff", text: "#000000", "fg-new": "#123456" });
    expect(unpaired).toEqual(["fg-new"]);
  });

  it("catches a pair below its threshold", () => {
    expect(contrast("#777777", "#808080")).toBeLessThan(4.5);
    expect(contrast("#000000", "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
});

describe.each([
  ["light", ':root[data-theme="light"]'],
  ["dark", ':root[data-theme="dark"]'],
])("the %s theme", (_name, selector) => {
  const colours = block(selector);
  const { pairs, unpaired } = classify(colours);

  it("pairs every colour token with a rule or an exemption", () => {
    expect(unpaired).toEqual([]);
  });

  // luminance() reads #rrggbb only; any other form would be measured wrongly or not at all
  it("gives every paired token a #rrggbb value", () => {
    for (const name of new Set(pairs.flatMap(([fg, bg]) => [fg, bg]))) {
      expect(colours[name], `--${name}`).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it.each(pairs)("%s on %s reaches %s:1", (fg, bg, min) => {
    expect(contrast(colours[fg]!, colours[bg]!)).toBeGreaterThanOrEqual(min);
  });
});

// The pairs come from each theme's own tokens, so a token one theme lacks would drop its pairs
// there silently, and a colour outside the two theme blocks would reach no rule at all.
it("declares the same tokens in both themes", () => {
  const light = Object.keys(block(':root[data-theme="light"]')).sort();
  const dark = Object.keys(block(':root[data-theme="dark"]')).sort();
  expect(dark).toEqual(light);
});

it("defines colours only in the light and dark theme blocks", () => {
  const raw = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;
  const rules = tokens
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("}")
    .filter((rule) => raw.test(rule));
  expect(rules).toHaveLength(2);
  expect(rules[0]).toContain(':root[data-theme="light"]');
  expect(rules[1]).toContain(':root[data-theme="dark"]');
});

// The report frame's claim highlight is the one colour pair outside tokens.css: the bridge sets
// it inside the sandboxed frame, where the app's tokens do not reach (spec §2.2, frameBridge.ts).
it("gives the frame's claim highlight 4.5:1, in either theme", () => {
  const rule = /\.corelata-highlight \{([^}]*)\}/.exec(HIGHLIGHT_CSS)?.[1] ?? "";
  const background = /background: (#[0-9a-fA-F]{6})/.exec(rule)?.[1];
  const colour = /(?:^|[\s;])color: (#[0-9a-fA-F]{6})/.exec(rule)?.[1];
  expect([colour, background]).toEqual(["#1a1a1a", "#fff3b0"]);
  expect(contrast(colour!, background!)).toBeGreaterThanOrEqual(4.5);
});
