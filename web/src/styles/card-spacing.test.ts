import { readdirSync, readFileSync } from "node:fs";

// Read from disk: Vitest serves stylesheets imported with ?raw as empty strings
// (tests run from web/).
const dir = "src/styles";
const sheets = readdirSync(dir).filter((name) => name.endsWith(".css"));

/** The selectors of every rule that sets a `.card`'s margin. */
function cardMarginSelectors(css: string): string[] {
  const rules = [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^}]*)\}/g)];
  return rules
    .filter(([, , body]) => /\bmargin(-bottom)?\s*:/.test(body!))
    .flatMap(([, selectors]) => selectors!.split(",").map((s) => s.trim()))
    .filter((s) => /\.card\b/.test(s));
}

it.each(sheets.filter((name) => name !== "base.css"))(
  "%s changes a card's margin only on its own page, so base.css's card margin holds elsewhere",
  (name) => {
    for (const selector of cardMarginSelectors(readFileSync(`${dir}/${name}`, "utf8"))) {
      expect(selector).not.toBe(".card");
      expect(selector).toMatch(/^\.[\w-]+\s*>?\s*\.card$/);
    }
  },
);

it("keeps base.css's one margin for a card", () => {
  expect(cardMarginSelectors(readFileSync(`${dir}/base.css`, "utf8"))).toEqual([
    ".card",
    ".settings > .card",
  ]);
});
