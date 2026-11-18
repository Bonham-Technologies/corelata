// Checks the static site in site/public: links and asset references, page metadata, the
// sitemap, the home page's JSON-LD, the Vercel config, sizes, and axe (WCAG 2.0 A/AA, 2.1 AA) at
// 1280 px and 360 px.
// It serves site/public on a free local port with the headers vercel.json sets, so a
// Content-Security-Policy violation or any request that leaves the site fails the check.
//
//   node site/check.mjs            (Node 22; uses Playwright and axe from web/node_modules)
//
// Set CHROMIUM_PATH to use another Chromium; the default is /opt/pw-browsers/chromium when it
// exists, otherwise Playwright's own browser.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { dirname, extname, join, normalize, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "public");
const ORIGIN = "https://corelata.com";
const REPO_URL = "https://github.com/Bonham-Technologies/corelata";
const MAX_BYTES = 6 * 1024 * 1024;
// Product exports copied verbatim from a run: link-checked and audited, but they are not site
// pages, so they carry no description or canonical of their own.
const EXPORTS = new Set(["sample/files/report.html"]);
const WIDTHS = [1280, 360];
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

const require = createRequire(join(HERE, "..", "web", "package.json"));
const { chromium } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const failures = [];
const fail = (where, message) => failures.push(`${where}: ${message}`);
const log = (message) => console.log(message);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".md": "text/markdown; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".vtt": "text/vtt; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".webm": "video/webm",
  ".woff2": "font/woff2",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

const files = walk(ROOT).map((path) => relative(ROOT, path).split(sep).join("/"));
const pages = files.filter((file) => file.endsWith(".html"));

/** The file a URL path names, as Vercel would serve it (a directory serves its index.html). */
function fileFor(pathname) {
  let path = decodeURIComponent(pathname).replace(/^\/+/, "");
  if (path === "" || path.endsWith("/")) path += "index.html";
  const full = normalize(join(ROOT, path));
  if (!full.startsWith(ROOT + sep)) return null;
  if (existsSync(full) && statSync(full).isFile()) return full;
  const index = join(full, "index.html");
  return existsSync(index) ? index : null;
}

// vercel.json: the headers it sets, the rules a deploy depends on
const vercel = JSON.parse(readFileSync(join(HERE, "vercel.json"), "utf-8"));
const headerRules = vercel.headers.map((rule) => ({
  pattern: new RegExp(`^${rule.source}$`),
  headers: rule.headers,
}));

function headersFor(pathname) {
  const out = {};
  for (const rule of headerRules) {
    if (rule.pattern.test(pathname)) for (const h of rule.headers) out[h.key] = h.value;
  }
  return out;
}

function checkVercel() {
  const where = "vercel.json";
  if (vercel.outputDirectory !== "public") fail(where, "outputDirectory is not public");
  if (!/git diff --quiet HEAD\^ HEAD -- \./.test(vercel.ignoreCommand ?? ""))
    fail(where, "ignoreCommand does not skip deploys when site/ is unchanged");
  if (vercel.env || vercel.build?.env) fail(where, "sets environment variables");
  for (const page of pages) {
    const pathname = "/" + page;
    const h = headersFor(pathname);
    const csp = h["Content-Security-Policy"] ?? "";
    if (!/frame-ancestors 'none'/.test(csp)) fail(where, `${pathname}: no frame-ancestors 'none'`);
    if (/'unsafe-inline'|'unsafe-eval'/.test(csp)) fail(where, `${pathname}: unsafe CSP source`);
    if (!EXPORTS.has(page) && !/default-src 'self'/.test(csp))
      fail(where, `${pathname}: CSP default-src is not 'self'`);
    if (h["X-Robots-Tag"])
      fail(where, `${pathname}: sends X-Robots-Tag, so it would not be indexed`);
    for (const key of [
      "Strict-Transport-Security",
      "X-Content-Type-Options",
      "Referrer-Policy",
      "Permissions-Policy",
    ]) {
      if (!h[key]) fail(where, `${pathname}: no ${key}`);
    }
  }
}

function checkStatic() {
  const sitemap = readFileSync(join(ROOT, "sitemap.xml"), "utf-8");
  const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  if (locs.length === 0) fail("sitemap.xml", "no <loc> entries");
  for (const loc of locs) {
    if (!loc.startsWith(ORIGIN + "/")) fail("sitemap.xml", `${loc} is not on ${ORIGIN}`);
    else if (!fileFor(new URL(loc).pathname)) fail("sitemap.xml", `${loc} has no page`);
  }
  const robots = readFileSync(join(ROOT, "robots.txt"), "utf-8");
  if (!robots.includes(`Sitemap: ${ORIGIN}/sitemap.xml`)) fail("robots.txt", "no Sitemap line");
  if (/^\s*Disallow:\s*\/\s*$/im.test(robots)) fail("robots.txt", "disallows the whole site");
  for (const name of ["404.html", "favicon.ico", "favicon.svg", "og.png"]) {
    if (!files.includes(name)) fail(name, "missing");
  }
  const og = readFileSync(join(ROOT, "og.png"));
  const [w, h] = [og.readUInt32BE(16), og.readUInt32BE(20)];
  if (w !== 1200 || h !== 630) fail("og.png", `is ${w}x${h}, not 1200x630`);
  const total = files.reduce((sum, file) => sum + statSync(join(ROOT, file)).size, 0);
  log(`site/public: ${files.length} files, ${(total / 1024 / 1024).toFixed(2)} MB`);
  if (total > MAX_BYTES) fail("site/public", `is ${total} bytes, over ${MAX_BYTES}`);
}

// The home page's structured data (CRL-98): one JSON-LD block naming the publisher and the product.
const ORG_URL = "https://bonham.tech/";
const APACHE = "https://www.apache.org/licenses/LICENSE-2.0";

function checkJsonLd() {
  const where = "index.html JSON-LD";
  const html = readFileSync(join(ROOT, "index.html"), "utf-8");
  // Any <script> whose type is application/ld+json, whatever its other attributes or quoting.
  const blocks = [
    ...html.matchAll(
      /<script\b[^>]*\btype\s*=\s*["']?application\/ld\+json["']?[^>]*>([\s\S]*?)<\/script\s*>/gi,
    ),
  ];
  if (blocks.length !== 1) return fail(where, `${blocks.length} application/ld+json blocks, not 1`);
  let data;
  try {
    data = JSON.parse(blocks[0][1]);
  } catch (error) {
    return fail(where, `does not parse: ${error.message}`);
  }
  if (typeof data !== "object" || data === null) return fail(where, "is not a JSON object");
  if (data["@context"] !== "https://schema.org") fail(where, "@context is not https://schema.org");
  const nodes = Array.isArray(data["@graph"]) ? data["@graph"] : [data];
  const ofType = (type) => nodes.filter((n) => n?.["@type"] === type);
  const isUrl = (value) => typeof value === "string" && /^https:\/\/\S+$/.test(value);
  const filled = (value) => typeof value === "string" && value.trim() !== "";

  const orgs = ofType("Organization");
  if (orgs.length !== 1) return fail(where, `${orgs.length} Organization nodes, not 1`);
  const org = orgs[0];
  if (!filled(org.name)) fail(where, "Organization has no name");
  if (org.url !== ORG_URL) fail(where, `Organization url is ${org.url}, not ${ORG_URL}`);
  if (!isUrl(org.logo)) fail(where, "Organization has no https logo");

  const apps = ofType("SoftwareApplication");
  if (apps.length !== 1) return fail(where, `${apps.length} SoftwareApplication nodes, not 1`);
  const app = apps[0];
  for (const key of ["name", "description", "applicationCategory", "operatingSystem"]) {
    if (!filled(app[key])) fail(where, `SoftwareApplication has no ${key}`);
  }
  if (app.url !== ORIGIN + "/")
    fail(where, `SoftwareApplication url is ${app.url}, not ${ORIGIN}/`);
  if (app.license !== APACHE)
    fail(where, `SoftwareApplication license is ${app.license}, not ${APACHE}`);
  const publisher = app.publisher ?? {};
  const named = org["@id"] && publisher["@id"] === org["@id"];
  if (!named && publisher.url !== ORG_URL)
    fail(where, "SoftwareApplication publisher is not the Organization");
  if (app.offers !== undefined) {
    const offers = Array.isArray(app.offers) ? app.offers : [app.offers];
    const valid = (o) =>
      o?.["@type"] === "Offer" &&
      o.price !== undefined &&
      o.price !== null &&
      filled(o.priceCurrency);
    if (offers.length === 0 || !offers.every(valid))
      fail(where, "SoftwareApplication offers is not an Offer with a price and a currency");
  }
  log(`ok   JSON-LD: ${org.name}; ${app.name}`);
}

function serve() {
  const server = createServer((request, response) => {
    const { pathname } = new URL(request.url, "http://localhost");
    const file = fileFor(pathname);
    const status = file ? 200 : 404;
    const body = readFileSync(file ?? join(ROOT, "404.html"));
    const served = file ? "/" + relative(ROOT, file).split(sep).join("/") : "/404.html";
    response.writeHead(status, {
      "Content-Type": TYPES[extname(file ?? "x.html")] ?? "application/octet-stream",
      ...headersFor(pathname.endsWith("/") ? served : pathname),
    });
    response.end(body);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

/** Every URL a page refers to, from the rendered DOM and its stylesheets. */
async function references(page) {
  return page.evaluate(() => {
    const refs = [];
    const add = (url, what) => url && refs.push({ url, what });
    for (const el of document.querySelectorAll("[href]:not(link[rel=canonical])"))
      add(el.getAttribute("href"), el.tagName);
    for (const el of document.querySelectorAll("[src]")) add(el.getAttribute("src"), el.tagName);
    for (const el of document.querySelectorAll("[poster]"))
      add(el.getAttribute("poster"), "poster");
    for (const el of document.querySelectorAll("[srcset]")) {
      for (const part of el.getAttribute("srcset").split(","))
        add(part.trim().split(/\s+/)[0], "srcset");
    }
    for (const sheet of document.styleSheets) {
      let rules = [];
      try {
        rules = [...sheet.cssRules];
      } catch {
        continue;
      }
      for (const rule of rules) {
        for (const m of rule.cssText.matchAll(/url\("?([^")]+)"?\)/g)) {
          add(new URL(m[1], sheet.href ?? document.baseURI).href, "css");
        }
      }
    }
    return refs;
  });
}

async function checkPage(browser, base, file) {
  const pathname =
    file === "index.html"
      ? "/"
      : file.endsWith("/index.html")
        ? "/" + file.slice(0, -10)
        : "/" + file;
  const isExport = EXPORTS.has(file);
  for (const width of WIDTHS) {
    const where = `${pathname} @${width}px`;
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    const problems = [];
    page.on("console", (message) => {
      if (message.type() === "error" || /Content Security Policy/i.test(message.text()))
        problems.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
    page.on("request", (request) => {
      if (!request.url().startsWith(base) && !request.url().startsWith("data:"))
        problems.push(`request leaves the site: ${request.url()}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`);
    });
    const response = await page.goto(base + pathname, { waitUntil: "load" });
    if (response.status() !== 200) problems.push(`HTTP ${response.status()}`);
    await page.evaluate(() => document.fonts.ready);
    // lazy images: load every one now, so each is checked too
    await page.evaluate(async () => {
      const imgs = [...document.images];
      for (const img of imgs) img.loading = "eager";
      await Promise.all(imgs.map((img) => img.decode().catch(() => {})));
    });
    await page.waitForLoadState("networkidle");
    const broken = await page.$$eval("img", (imgs) =>
      imgs
        .filter((img) => !(img.complete && img.naturalWidth > 0))
        .map((img) => img.currentSrc || img.src),
    );
    for (const src of broken) problems.push(`image did not load: ${src}`);

    if (width === WIDTHS[0]) {
      // metadata
      const meta = await page.evaluate(() => ({
        lang: document.documentElement.lang,
        title: document.title.trim(),
        description: document.querySelector('meta[name="description"]')?.content?.trim() ?? "",
        canonical: document.querySelector('link[rel="canonical"]')?.href ?? "",
        h1: document.querySelectorAll("h1").length,
        robots: document.querySelector('meta[name="robots"]')?.content ?? "",
        ids: [...document.querySelectorAll("[id]")].map((el) => el.id),
      }));
      if (!meta.lang) problems.push("no lang on <html>");
      if (!meta.title) problems.push("no <title>");
      if (file !== "404.html" && /noindex|none/i.test(meta.robots))
        problems.push(`meta robots is ${meta.robots}`);
      // every page, the verbatim export too, names its own public URL (seo-check SEO-9)
      if (!meta.canonical.startsWith(ORIGIN + "/"))
        problems.push(`canonical is ${meta.canonical || "missing"}`);
      if (!isExport) {
        if (!meta.description) problems.push("no meta description");
        if (meta.h1 !== 1) problems.push(`${meta.h1} <h1> elements`);
      }
      const seen = new Set();
      for (const id of meta.ids) {
        if (seen.has(id)) problems.push(`duplicate id ${id}`);
        seen.add(id);
      }
      // links and asset references
      for (const { url, what } of await references(page)) {
        if (/^(mailto:|tel:)/.test(url)) continue;
        const target = new URL(url, base + pathname);
        if (target.origin !== new URL(base).origin) {
          if (what !== "A") problems.push(`${what} loads from another origin: ${url}`);
          // The only GitHub link the site may carry is the public repository itself.
          if (target.hostname === "github.com" && target.href.replace(/\/$/, "") !== REPO_URL)
            problems.push(`links to GitHub other than the repository: ${url}`);
          continue;
        }
        const targetFile = fileFor(target.pathname);
        if (!targetFile) {
          problems.push(`${what} ${url} does not resolve`);
          continue;
        }
        if (target.hash && targetFile.endsWith(".html")) {
          const id = decodeURIComponent(target.hash.slice(1));
          const html = readFileSync(targetFile, "utf-8");
          if (!new RegExp(`id="${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`).test(html))
            problems.push(`${url}: no element with id ${id}`);
        }
      }
    }

    // nothing wider than the viewport
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    if (scrollWidth > width) problems.push(`scrolls sideways: ${scrollWidth}px wide`);

    const axe = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    for (const v of axe.violations) {
      const targets = v.nodes
        .map((n) => n.target.join(" "))
        .slice(0, 3)
        .join("; ");
      problems.push(`axe ${v.id} (${v.impact}): ${v.help} [${targets}]`);
    }
    log(
      `${problems.length ? "FAIL" : "ok  "} ${where}: axe ${axe.passes.length} rules passed, ${axe.violations.length} violations`,
    );
    for (const p of problems) fail(where, p);
    await context.close();
  }
}

async function checkNotFound(browser, base) {
  const page = await browser.newPage();
  const response = await page.goto(base + "/no-such-page/");
  if (response.status() !== 404) fail("/no-such-page/", `HTTP ${response.status()}, not 404`);
  else if (!(await page.title()).includes("not found"))
    fail("/no-such-page/", "is not the 404 page");
  else log("ok   unknown paths get 404.html with status 404");
  await page.close();
}

checkVercel();
checkStatic();
checkJsonLd();
const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
log(`serving site/public at ${base}`);
const executablePath =
  process.env.CHROMIUM_PATH ??
  (existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
const browser = await chromium.launch({ executablePath });
try {
  for (const file of pages) await checkPage(browser, base, file);
  await checkNotFound(browser, base);
} finally {
  await browser.close();
  server.close();
}

if (failures.length) {
  console.error(`\n${failures.length} problem(s):`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
log(`\nall checks passed: ${pages.length} pages at ${WIDTHS.join(" and ")} px`);
