import { expect, test, type Page } from "@playwright/test";
import { startRun } from "./support";

// M18 spec §8.3: dark mode before the first paint, on every screen, and inside the report frame,
// which follows the app's theme rather than the computer's (R-M18-2).

/** Stores the theme before the app loads, and records data-theme when <body> is first parsed.
 * A blocking script in <head> has run by then; a deferred, async or module one has not (checked
 * by making theme-init.js each of those: the test fails every time). That is the proof offered
 * for "no light flash": it does not measure a paint. */
async function chooseTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((choice) => {
    localStorage.setItem("corelata.theme", choice);
    new MutationObserver((_, observer) => {
      if (!document.body) return;
      (window as unknown as { themeAtBody?: string }).themeAtBody =
        document.documentElement.dataset.theme;
      observer.disconnect();
    }).observe(document, { childList: true, subtree: true });
  }, theme);
}

/** The computed colour of one of the app's tokens, in the page's current theme. */
async function token(page: Page, name: string): Promise<string> {
  return page.evaluate((property) => {
    const probe = document.createElement("div");
    probe.style.backgroundColor = `var(${property})`;
    document.body.append(probe);
    const colour = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return colour;
  }, name);
}

test("a stored dark theme applies before the first paint, on every screen and in the report", async ({
  page,
  request,
}) => {
  await chooseTheme(page, "dark"); // the computer stays light: Chromium's default
  const { projectId, runId } = await startRun(request, { label: "Theme", maxIterations: 0 });
  for (const path of ["/new", `/new?project=${projectId}`, `/runs/${runId}`, "/settings"]) {
    await page.goto(path);
    expect(
      await page.evaluate(() => (window as unknown as { themeAtBody?: string }).themeAtBody),
      `${path}: data-theme was already dark when <body> was parsed`,
    ).toBe("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("body")).toHaveCSS("background-color", await token(page, "--bg"));
  }
  await page.goto(`/runs/${runId}`);
  await page.getByRole("link", { name: "Review the report" }).click({ timeout: 90_000 });
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  await expect(frame.locator("html")).toHaveClass(/\bcorelata-theme-dark\b/);
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(page.locator('iframe[title="Report"]')).toHaveCSS(
    "background-color",
    await token(page, "--surface"),
  );
  // the toggle switches the report too, without reloading it
  await page.getByRole("button", { name: "Switch to the light theme" }).click();
  await expect(frame.locator("html")).toHaveClass(/\bcorelata-theme-light\b/);
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(0, 0, 0)");
});

test("a light app on a dark computer shows the report light", async ({ page, request }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await chooseTheme(page, "light");
  const { runId } = await startRun(request, { label: "Theme", maxIterations: 0 });
  await page.goto(`/runs/${runId}`);
  await page.getByRole("link", { name: "Review the report" }).click({ timeout: 90_000 });
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(frame.locator("html")).toHaveClass(/\bcorelata-theme-light\b/);
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(0, 0, 0)");
});
