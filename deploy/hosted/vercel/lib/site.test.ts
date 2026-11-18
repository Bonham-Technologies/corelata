import { readFileSync } from "node:fs";
import { join } from "node:path";
import axe from "axe-core";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it } from "vitest";

// Corelata's checks on the site's static files (spec §12.2): the policy every page is served
// with, and the sign-in page's colours.
const HERE = join(__dirname, "..");
const REPO = join(HERE, "..", "..", "..");
const read = (path: string) => readFileSync(path, "utf8");

describe("vercel.json", () => {
  const config = JSON.parse(read(join(HERE, "vercel.json"))) as {
    headers: { source: string; headers: { key: string; value: string }[] }[];
  };

  it("sends the operator guide's sample Content-Security-Policy on every path, word for word", () => {
    // The guide's nginx line, which api/tests/test_csp_proxy.py pins for the e2e proxy too.
    const guide = read(join(REPO, "docs", "operator-guide.md"));
    const sample = /add_header Content-Security-Policy "([^"]+)" always;/.exec(guide)?.[1];
    expect(sample).toBeTruthy();
    const everyPath = config.headers.filter((h) => h.source === "/(.*)");
    expect(everyPath).toHaveLength(1);
    const policies = everyPath[0].headers.filter((h) => h.key === "Content-Security-Policy");
    expect(policies.map((h) => h.value)).toEqual([sample]);
  });
});

describe("robots.txt", () => {
  // The demo is a private sign-in page: crawlers are turned away from all of it (CRL-98).
  it("disallows everything for every crawler", () => {
    const robots = read(join(HERE, "static", "robots.txt"));
    expect(robots.split("\n").filter((l) => l.trim())).toEqual(["User-agent: *", "Disallow: /"]);
  });

  it("is copied into the deployed site", () => {
    expect(read(join(HERE, "build.sh"))).toContain('cp "$here/static/robots.txt" "$here/public/robots.txt"');
  });
});

describe("login.html", () => {
  // Every --name: value pair of a :root[data-theme="…"] block, in order.
  const theme = (css: string, which: "light" | "dark") => {
    const start = css.indexOf(`:root[data-theme="${which}"]`);
    const block = css.slice(start, css.indexOf("}", start));
    return Object.fromEntries([...block.matchAll(/(--[a-z-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  };
  const login = read(join(HERE, "static", "login.html"));
  const tokens = read(join(REPO, "web", "src", "styles", "tokens.css"));

  it.each(["light", "dark"] as const)("uses the web app's %s colours", (which) => {
    const used = theme(login, which);
    expect(Object.keys(used).length).toBeGreaterThanOrEqual(8);
    const app = theme(tokens, which);
    for (const [name, value] of Object.entries(used)) expect([name, app[name]]).toEqual([name, value]);
  });

  it("names none of the web app's bundled fonts without loading it", () => {
    // The app bundles its fonts from @fontsource; the sign-in page can't reach those hashed
    // files, so naming one here would silently fall back to the next family (CRL-60).
    const pkg = JSON.parse(read(join(REPO, "web", "package.json"))) as { dependencies: Record<string, string> };
    const bundled = Object.keys(pkg.dependencies)
      .filter((d) => d.startsWith("@fontsource/"))
      .map((d) => d.slice("@fontsource/".length).split("-"))
      .map((words) => words.map((w) => w[0].toUpperCase() + w.slice(1)).join(" "));
    expect(bundled).toContain("Noto Sans");
    // CSS family names match case-insensitively and may be quoted either way.
    const family = (f: string) => f.trim().replace(/^["']|["']$/g, "").toLowerCase();
    const declared = [...login.matchAll(/@font-face\s*{[^}]*font-family:\s*([^;}]+)/g)].map((m) => family(m[1]));
    const named = [...login.matchAll(/font-family:\s*([^;}]+)/g)].flatMap((m) => m[1].split(",").map(family));
    expect(bundled.filter((f) => named.includes(family(f)) && !declared.includes(family(f)))).toEqual([]);
  });

  it("is Corelata's and keeps the theme under Corelata's key", () => {
    expect(login).toContain("Corelata</h1>");
    expect(login).toContain('localStorage.getItem("corelata.theme")');
  });

  // The page with its own scripts run, at the address a sign-in failure redirects to.
  const opened: JSDOM[] = [];
  const open = (search: string) => {
    const dom = new JSDOM(login, { runScripts: "dangerously", url: `https://front.example/login${search}` });
    opened.push(dom);
    return dom;
  };
  afterEach(() => {
    for (const dom of opened.splice(0)) dom.window.close();
  });

  it("names the task in its only heading", () => {
    const doc = open("").window.document;
    expect([...doc.querySelectorAll("h1")].map((h) => h.textContent)).toEqual(["Sign in to Corelata"]);
  });

  it("hides the failure by default and announces it as an alert", () => {
    const doc = open("").window.document;
    const error = doc.querySelector(".error") as HTMLElement;
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.hidden).toBe(true);
    expect(doc.querySelector('input[name="name"]')?.hasAttribute("aria-describedby")).toBe(false);
  });

  it("after a failed sign-in shows the error and puts focus on the name field", () => {
    const doc = open("?failed=1").window.document;
    const error = doc.querySelector(".error") as HTMLElement;
    const name = doc.querySelector('input[name="name"]') as HTMLInputElement;
    expect(error.hidden).toBe(false);
    expect(doc.activeElement).toBe(name);
    // Read out with the field, since an alert shown during page load may not be announced.
    expect(doc.getElementById(name.getAttribute("aria-describedby") ?? "")).toBe(error);
  });

  it("passes axe, with and without the error shown", async () => {
    for (const search of ["", "?failed=1"]) {
      const { window } = open(search);
      const results = await axe.run(window.document.documentElement, {
        rules: { "color-contrast": { enabled: false } }, // jsdom computes no layout or colours
      });
      expect(results.violations.map((v) => v.id)).toEqual([]);
    }
  });
});
