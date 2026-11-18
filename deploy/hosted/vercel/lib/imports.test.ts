import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Vercel runs middleware.ts as a Node ES module, which does not add extensions to relative
// imports; vitest does, so only this test catches a missing one.
const ROOT = join(__dirname, "..");
const files = [
  "middleware.ts",
  ...readdirSync(join(ROOT, "lib"))
    .filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"))
    .map((f) => `lib/${f}`),
];

describe("deployed relative imports", () => {
  it("finds the files to check", () => {
    expect(files).toContain("lib/route.ts");
  });

  it.each(files)("%s gives every relative import a .js extension", (file) => {
    const source = readFileSync(join(ROOT, file), "utf8");
    const specs = [...source.matchAll(/\bfrom\s+["'](\.{1,2}\/[^"']*)["']/g)].map((m) => m[1]);
    expect(specs.filter((s) => !s.endsWith(".js"))).toEqual([]);
  });
});
