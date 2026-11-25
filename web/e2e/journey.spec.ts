import { expect, test, type Page } from "@playwright/test";
import { PORT_TEXT } from "./support";

// The writing page's steps: waiting to start, the six stages, ready to review.
const STEP_COUNT = 1 + 6 + 1;

function watchRequests(page: Page, origin: string): string[] {
  const foreign: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith(origin)) foreign.push(request.url());
  });
  return foreign;
}

test("a new project, upload, suggest value, write, review, return and the revised report", async ({
  page,
  baseURL,
}) => {
  const foreign = watchRequests(page, baseURL!);
  await page.goto("/");
  await expect(page).toHaveURL(/\/new$/);
  await expect(page).toHaveTitle("New report – Corelata");

  // New report: a new project, then its page (M18 spec §5.1, §5.2).
  await page.getByRole("button", { name: "New project" }).click();
  const name = `Journey ${Date.now()}`;
  await page.getByRole("textbox", { name: "Project name" }).fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Your projects" })
      .getByRole("link", { name: new RegExp(`^${name}`) }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Sources" })).toBeVisible();
  await page.getByLabel("Choose files").setInputFiles({
    name: "port.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(PORT_TEXT, "utf-8"),
  });
  await expect(page.getByRole("list", { name: "Chosen files" })).toContainText("port.txt");
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked();

  await page.getByRole("button", { name: "Suggest value" }).click();
  const suggestions = page.getByRole("list", { name: "Suggested value statements" });
  await expect(suggestions).toBeVisible();
  // the discovery is in the URL: a reload reads it again (R-M16-14)
  await expect(page).toHaveURL(/[?&]discovery=[0-9a-f-]+/);
  await page.reload();
  await expect(suggestions).toBeVisible();
  await suggestions.getByRole("button", { name: "Use this statement" }).first().click();
  const statement = page.getByRole("textbox", { name: "Value statement" });
  await expect(statement).not.toHaveValue("");
  await page.locator("summary", { hasText: "More options" }).click();
  await page.getByRole("spinbutton", { name: "Revision rounds" }).fill("1");
  await page.getByRole("button", { name: "Write the report" }).click();

  // Screen 2: the steps advance and end with the review link.
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByRole("list", { name: "Steps" })).toBeVisible();
  const review = page.getByRole("link", { name: "Review the report" });
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("heading", { name: "Ready to review." })).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Steps" }).locator('[data-status="done"]'),
  ).toHaveCount(STEP_COUNT);
  await expect(page).toHaveTitle(/^✓ Ready to review – /);
  await page.locator("summary", { hasText: "Details" }).click();
  await expect(page.getByRole("status", { name: "Token usage" })).toContainText("model calls");
  await review.click();

  // Screen 3: report, provenance, audit, downloads.
  await expect(page).toHaveURL(/\/review$/);
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  const claims = page.getByRole("list", { name: "Claims" });
  await claims.getByRole("button").first().click();
  await expect(page.getByRole("list", { name: /^Evidence for / })).toBeVisible();
  // CRL-93: the dev stack quotes evidence (evidence_quotes: required); the quote is marked
  await expect(
    page
      .getByRole("list", { name: /^Evidence for / })
      .locator("mark")
      .first(),
  ).toBeVisible();
  await expect(frame.locator(".corelata-highlight").first()).toBeVisible();
  // a click on a cited element inside the real frame reaches the page through the bridge
  await page.getByRole("tab", { name: "Standards" }).click();
  await frame.locator("[data-claim-ids]:not([data-claim-ids=''])").first().click();
  await expect(page).toHaveURL(/claim=/);
  await expect(page.getByRole("tab", { name: "Claims" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Standards" }).click();
  await expect(page.getByRole("tabpanel").locator(".rule").first()).toBeVisible();
  await page.getByRole("tab", { name: "Process" }).click();
  await expect(page.getByRole("table", { name: "Stage timeline" })).toBeVisible();
  await page.getByRole("tab", { name: "Sources" }).click();
  await expect(page.getByRole("table", { name: "Sources" })).toContainText("port.txt");

  await page.getByRole("button", { name: "Download" }).click();
  const items = page.getByRole("menu", { name: "Download" }).getByRole("menuitem");
  await expect(items).toHaveText([
    "Word document (DOCX)",
    "Markdown",
    "Web page (HTML)",
    "Trace (JSON)",
  ]);
  const types = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/html",
    "application/json",
  ];
  for (const [i, type] of types.entries()) {
    const href = await items.nth(i).getAttribute("href");
    const response = await page.request.get(href!);
    expect(response.status(), type).toBe(200);
    expect(response.headers()["content-type"], type).toContain(type);
  }
  await page.keyboard.press("Escape");

  // Return with a note: a linked child run starts and completes.
  const originalUrl = new URL(page.url()).pathname;
  // the heading reads "Report" until the report's title is read
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText("Report");
  const originalTitle = await page.getByRole("heading", { level: 1 }).textContent();
  const note = "Add the 2027 date to the title.";
  await page.getByRole("button", { name: "Return with note…" }).click();
  await page.getByRole("textbox", { name: "Note for the writer" }).fill(note);
  await page.getByRole("button", { name: "Return", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByRole("link", { name: "Review the report" })).toBeVisible({
    timeout: 90_000,
  });

  // The revised report names its original, links back to it, and shows the note (CRL-102).
  await page.getByRole("link", { name: "Review the report" }).click();
  await expect(page).toHaveURL(/\/review$/);
  const original = page.getByRole("region", { name: "Original report" });
  await expect(original).toContainText(`Revision of ${originalTitle!}`);
  await expect(original.getByRole("region", { name: "Note for the writer" })).toContainText(note);
  await expect(original.getByRole("link", { name: originalTitle! })).toHaveAttribute(
    "href",
    originalUrl,
  );
  // Accept asks first (CRL-127): Cancel records nothing and returns to the button; confirming
  // decides the report and moves focus to the banner.
  const accept = page.getByRole("button", { name: "Accept", exact: true });
  await accept.click();
  const confirm = page.getByRole("dialog", { name: "Accept this report?" });
  await expect(confirm).toContainText("can't be returned");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toBeHidden();
  await expect(accept).toBeFocused();
  await expect(accept).toBeEnabled();
  await accept.click();
  await confirm.getByRole("button", { name: "Accept report" }).click();
  const banner = page.getByRole("status", { name: "Where the review stands" });
  await expect(banner).toContainText("Accepted");
  await expect(banner).toBeFocused();
  // the project's Reports list marks it
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link").click();
  await expect(
    page.getByRole("list", { name: "Reports" }).getByRole("listitem").first(),
  ).toContainText("Revised report");

  expect(foreign, "every request stayed on the app's origin").toEqual([]);
});

test("a reload keeps the project, the tab and the selected claim", async ({ page }) => {
  await page.goto("/new");
  const picker = page.getByRole("combobox", { name: "Project" });
  const projectName = await picker.locator("option").nth(1).textContent();
  await picker.selectOption({ index: 1 });
  await expect(page).toHaveURL(/\?project=/);
  await page.reload();
  // the project page names the project, not the picker's question
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(projectName!);
  await page.getByRole("link", { name: "Review", exact: true }).first().click();
  const claims = page.getByRole("list", { name: "Claims" });
  await claims.getByRole("button").first().click();
  await expect(page).toHaveURL(/claim=/);
  await expect(claims.getByRole("button").first()).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("tab", { name: "Sources" }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/claim=/);
  await page.getByRole("tab", { name: "Claims" }).click();
  await expect(claims.getByRole("button").first()).toHaveAttribute("aria-pressed", "true");
});

test("a statement the sources do not support, then another from the same run (CRL-84)", async ({
  page,
}) => {
  await page.goto("/new");
  await page.getByRole("button", { name: "New project" }).click();
  const name = `Rejected ${Date.now()}`;
  await page.getByRole("textbox", { name: "Project name" }).fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByLabel("Choose files").setInputFiles({
    name: "port.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(PORT_TEXT, "utf-8"),
  });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked();
  const unsupported = "Penguin colonies thrive on Antarctic glaciers";
  await page.getByRole("textbox", { name: "Value statement" }).fill(unsupported);
  await page.getByRole("button", { name: "Write the report" }).click();

  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: "Not supported by the sources." })).toBeVisible({
    timeout: 90_000,
  });
  // the page says which statement the sources did not support (CRL-101)
  await expect(page.getByRole("region", { name: "Value statement" })).toContainText(unsupported);
  await page.getByRole("link", { name: "Try another statement" }).click();
  // the new report starts from the run, and `from` leaves the URL once it has
  await expect(page.getByRole("textbox", { name: "Value statement" })).toHaveValue(unsupported);
  await expect(page).toHaveURL(/\?project=[0-9a-f-]+&pick=/);
  await expect(page.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Value statement" })).toHaveValue(unsupported);
});

test("the Reports list fits a phone and leaves the statement room beside the sidebar (CRL-110)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/new");
  const picker = page.getByRole("combobox", { name: "Project" });
  await picker.selectOption({ index: 1 });
  await expect(page).toHaveURL(/\?project=/);
  await expect(page.getByRole("list", { name: "Reports" })).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits, "no sideways scroll at 360px").toBe(true);
  // the row stacks on the list's width: the statement is never squeezed to a sliver, on a phone
  // or at a laptop width with the sidebar open
  const statement = page.locator(".report-row .statement").first();
  for (const width of [360, 1000]) {
    await page.setViewportSize({ width, height: 800 });
    const box = await statement.boundingBox();
    expect(box?.width ?? 0, `statement width at ${width}px`).toBeGreaterThanOrEqual(200);
  }
});
