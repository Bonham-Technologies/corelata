import { readdirSync, readFileSync } from "node:fs";

// Read from disk: Vitest serves stylesheets imported with ?raw as empty strings
// (tests run from web/).
const dir = "src/styles";
const sheets = readdirSync(dir).filter((name) => name.endsWith(".css"));

// tokens.css defines the colours.
const ALLOWED = new Set(["tokens.css"]);
const RAW = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

it.each(sheets.filter((name) => !ALLOWED.has(name)))(
  "%s uses design values, not raw colours",
  (name) => {
    const css = readFileSync(`${dir}/${name}`, "utf8");
    expect(css.length).toBeGreaterThan(0);
    expect(css).not.toMatch(RAW);
  },
);
