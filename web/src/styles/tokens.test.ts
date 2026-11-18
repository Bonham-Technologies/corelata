import { readFileSync } from "node:fs";

// Read from disk: Vitest serves stylesheets imported with ?raw as empty strings
// (tests run from web/).
const tokens = readFileSync("src/styles/tokens.css", "utf8");

/** The selector lists of the rules that define the colours (they hold --bg). */
function colourSelectors(): string[] {
  return tokens
    .split("}")
    .filter((rule) => rule.includes("--bg:"))
    .map((rule) => rule.slice(0, rule.indexOf("{")).replace(/\/\*[\s\S]*?\*\//g, ""));
}

// A dialog's ::backdrop does not inherit custom properties in every browser, so the colour
// tokens are defined on it as well; otherwise var(--bg) there is empty and the page shows through.
it("defines the colour tokens on the dialog backdrop in both themes", () => {
  const [light, dark] = colourSelectors();
  expect(light).toContain("dialog::backdrop");
  expect(light).not.toContain("dark");
  expect(dark).toContain(':root[data-theme="dark"] dialog::backdrop');
});

// base.css takes its dialog and menu widths and its border width from tokens.css.
it("keeps raw sizes out of base.css", () => {
  const base = readFileSync("src/styles/base.css", "utf8");
  for (const name of ["dialog-width", "menu-min-width", "border-width"]) {
    expect(tokens, `--${name}`).toMatch(new RegExp(`--${name}:\\s*[\\d.]+(rem|px)\\s*;`));
  }
  expect(base).not.toMatch(/\b(36|14)rem\b/);
  expect(base).not.toMatch(/\bborder(-\w+)?:\s*[1-9]\d*px\b/);
});
