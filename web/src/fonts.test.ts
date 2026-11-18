// @vitest-environment node
import { readFileSync } from "node:fs";
import { FONT_FAMILIES } from "./fonts";

// Adapted from Coglossa's fonts.test.ts (spec §2.4): one family, Noto Sans.
const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {
  dependencies: Record<string, string>;
};
const fontsSource = readFileSync(new URL("./fonts.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("./styles/base.css", import.meta.url), "utf8");
const fontPackages = Object.keys(pkg.dependencies).filter((d) => d.startsWith("@fontsource/"));

it("depends on Noto Sans at the version Coglossa ships, and on no other font", () => {
  expect(pkg.dependencies["@fontsource/noto-sans"]).toBe("5.3.0");
  expect(fontPackages).toEqual(["@fontsource/noto-sans"]);
});

it("imports the regular and bold faces of every font package it depends on", () => {
  const imported = [...fontsSource.matchAll(/import "(@fontsource\/[^/]+)\/(\d+)\.css"/g)];
  expect(imported.map((m) => `${m[1]}/${m[2]}`)).toEqual([
    "@fontsource/noto-sans/400",
    "@fontsource/noto-sans/700",
  ]);
});

it("starts the page's font stack with Noto Sans and falls back to the computer's fonts", () => {
  const stack = /--font-stack:([^;]+);/.exec(css)?.[1] ?? "";
  const names = [...stack.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  expect(names[0]).toBe(FONT_FAMILIES[0]);
  expect(stack).toContain("system-ui");
  expect(stack.trim().endsWith("sans-serif")).toBe(true);
});
