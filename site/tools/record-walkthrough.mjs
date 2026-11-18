// Records the walkthrough against a running dev stack (api/devstack.py): the screenshots
// 01-06 as PNG, the WebM, and the time of each step (for the captions) on stdout.
// usage: node site/tools/record-walkthrough.mjs <baseURL> <outDir> <sourceFile> <statement>
// See site/README.md for the whole procedure.
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "..", "..", "web", "package.json"));
const { chromium } = require("@playwright/test");
const executablePath =
  process.env.CHROMIUM_PATH ??
  (existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);

const [baseURL, out, sourceFile, statement] = process.argv.slice(2);
mkdirSync(join(out, "video"), { recursive: true });
const size = { width: 1280, height: 1000 };

const browser = await chromium.launch({ executablePath });
const context = await browser.newContext({
  baseURL,
  viewport: size,
  colorScheme: "dark",
  recordVideo: { dir: join(out, "video"), size },
});
const page = await context.newPage();
const t0 = Date.now();
const marks = [];
const mark = (label) => marks.push({ label, s: (Date.now() - t0) / 1000 });
const pause = (ms = 1200) => page.waitForTimeout(ms);
const shot = async (name) => {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, `${name}.png`) });
};

mark("start");
await page.goto("/");
await page.waitForURL(/\/new$/);
await pause(1500);
mark("project");
await page.getByRole("button", { name: "New project" }).click();
await pause(600);
await page.getByRole("textbox", { name: "Project name" }).pressSequentially("Varna port", {
  delay: 60,
});
await pause(500);
await page.getByRole("button", { name: "Create" }).click();
await page.getByRole("region", { name: "Sources" }).waitFor();
await pause();
mark("upload");
await page.getByLabel("Choose files").setInputFiles({
  name: basename(sourceFile),
  mimeType: "text/plain",
  buffer: readFileSync(sourceFile),
});
await pause(800);
await page.getByRole("button", { name: "Upload" }).click();
await page.getByRole("checkbox", { name: `Use ${basename(sourceFile)} in this report` }).waitFor();
await pause();
mark("statement");
const box = page.getByRole("textbox", { name: "Value statement" });
await box.click();
await box.pressSequentially(statement, { delay: 18 });
await pause(800);
await shot("01-new-report");
await pause(800);
mark("write");
await page.getByRole("button", { name: "Write the report" }).click();

await page.waitForURL(/\/runs\/[0-9a-f-]+$/);
const steps = page.getByRole("list", { name: "Steps" });
await steps.waitFor();
// keep the latest frame that still shows a stage in progress
let best = null;
let preferred = null;
for (let i = 0; i < 600; i++) {
  const statuses = await steps.locator("li").evaluateAll((els) => els.map((e) => e.dataset.status));
  const now = statuses.indexOf("now");
  if (statuses.length > 0 && statuses.every((s) => s === "done")) break;
  if (now >= 2) {
    const png = await page.screenshot();
    const after = await steps.locator("li").evaluateAll((els) => els.map((e) => e.dataset.status));
    if (after.indexOf("now") === now) {
      best = png;
      if (now === 5 && !preferred) preferred = png;
    }
  }
  await page.waitForTimeout(40);
}
if (preferred || best) writeFileSync(join(out, "02-writing.png"), preferred || best);
const review = page.getByRole("link", { name: "Review the report" });
await review.waitFor({ timeout: 90_000 });
mark("ready");
await pause(1500);
await shot("03-ready");
await pause(800);
const runId = page.url().split("/runs/")[1];
mark("review");
await review.click();

await page.waitForURL(/\/review/);
const frame = page.frameLocator('iframe[title="Report"]');
await frame.locator("h1").waitFor();
await pause(1500);
const claims = page.getByRole("list", { name: "Claims" });
mark("claim");
await claims.getByRole("button").first().click();
await page.getByRole("list", { name: /^Evidence for / }).waitFor();
await frame.locator(".corelata-highlight").first().waitFor();
await pause(1500);
await shot("04-claims");
await pause(800);
mark("standards");
await page.getByRole("tab", { name: "Standards" }).click();
await page.getByRole("tabpanel").locator(".rule").first().waitFor();
await pause(1500);
await shot("05-standards");
await pause(800);
mark("sources");
await page.getByRole("tab", { name: "Sources" }).click();
await page.getByRole("table", { name: "Sources" }).waitFor();
await pause(1500);
await shot("06-sources");
await pause(1000);

mark("end");
const video = page.video();
await context.close();
await video.saveAs(join(out, "walkthrough-raw.webm"));
await browser.close();
console.log(JSON.stringify({ runId, marks }));
