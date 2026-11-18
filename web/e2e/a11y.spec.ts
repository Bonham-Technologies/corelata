import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { startRun } from "./support";

// CRL-50: every screen the journeys visit passes axe's WCAG 2.0/2.1 A and AA rules and its
// best-practice rules (among them `region`: all content sits in a landmark), in both themes.
// The first customer needs Section 508 / WCAG 2.1 AA; this keeps a regression from shipping.

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

/** Fails with each violated rule, its impact and the nodes it names. */
async function expectAccessible(page: Page, screen: string) {
  // the version line renders once the API answers; scan it, in a landmark, every time
  await expect(page.getByRole("contentinfo", { name: "Version" })).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const found = violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(found, `axe violations on ${screen}`).toEqual([]);
}

async function chooseTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((choice) => localStorage.setItem("corelata.theme", choice), theme);
}

type Progress = { state: string; stages: { stage: string }[] } & Record<string, unknown>;

const TERMINAL = new Set(["completed", "gate_rejected", "failed", "cancelled"]);

/** The run's progress once it has ended, polled through the API. */
async function settled(request: APIRequestContext, runId: string) {
  let progress: Progress | undefined;
  await expect
    .poll(
      async () => {
        progress = await (await request.get(`/api/runs/${runId}`)).json();
        return TERMINAL.has(progress!.state);
      },
      { timeout: 90_000 },
    )
    .toBe(true);
  return progress!;
}

/** A completed run's progress. */
async function completedRun(request: APIRequestContext, label: string) {
  const { runId } = await startRun(request, { label, maxIterations: 0 });
  const progress = await settled(request, runId);
  expect(progress.state, `${label}: the run's end`).toBe("completed");
  return progress;
}

/** A run a stop ended before its report was written. The worker honours a stop between steps,
 * so one asked for at once nearly always lands; on a machine slow enough for the run to finish
 * first (the stop is refused, or comes after the last step) another run is started, so the outcome
 * never rests on a race. */
async function stoppedRun(request: APIRequestContext, label: string) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    const named = `${label} (try ${attempt})`;
    const run = await startRun(request, { label: named, maxIterations: 0 });
    const stop = await request.post(`/api/runs/${run.runId}/cancel`);
    expect([200, 409], `${named}: the stop's answer`).toContain(stop.status());
    if ((await settled(request, run.runId)).state === "cancelled") return run;
  }
  throw new Error(`${label}: five runs finished before a stop reached them`);
}

/** A project's row in the sidebar. */
function projectLink(page: Page, projectId: string) {
  return page
    .getByRole("navigation", { name: "Your projects" })
    .locator(`a[href="/new?project=${projectId}"]`);
}

/** Holds the page's view of a run at the drafting step: the run's own progress and its event
 * stream answer with a snapshot made from the finished run's first two stages, and the project
 * list counts it as writing, as the sidebar would show it. The synthetic model finishes a run in
 * seconds, so the browser is shown a frozen copy instead of racing it. */
async function holdWriting(page: Page, finished: Progress) {
  const writing = {
    ...finished,
    state: "drafting",
    status: null,
    review: null,
    finished_at: null,
    stages: finished.stages.filter((s) => s.stage === "ingesting" || s.stage === "gating"),
  };
  const runId = finished["run_id"] as string;
  const projectId = finished["project_id"] as string;
  await page.route(`**/api/runs/${runId}`, (route) => route.fulfill({ json: writing }));
  await page.route(`**/api/runs/${runId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: `retry: 3000\n\nevent: progress\ndata: ${JSON.stringify(writing)}\n\n`,
    }),
  );
  await page.route("**/api/projects", async (route) => {
    const projects: Record<string, unknown>[] = await (await route.fetch()).json();
    const json = projects.map((p) =>
      p["id"] === projectId
        ? {
            ...p,
            reports_writing: 1,
            reports_to_review: 0,
            latest_run: { run_id: runId, state: "drafting", status: null, decision: null },
          }
        : p,
    );
    await route.fulfill({ json });
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`every screen passes axe in the ${theme} theme`, async ({ page, request }) => {
    await chooseTheme(page, theme);
    // Home, then the new-report screen it leads to. The e2e files run in order on one fresh
    // stack and this one comes first, so the light pass also scans the empty sidebar.
    await page.goto("/");
    await expect(page).toHaveURL(/\/new$/);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("heading", { name: "New report" })).toBeVisible();
    await expectAccessible(page, `/new (${theme})`);

    const { projectId, runId } = await startRun(request, {
      label: `Accessibility ${theme}`,
      maxIterations: 0,
    });
    await page.goto(`/new?project=${projectId}`);
    await expect(page.getByText("port.txt").first()).toBeVisible();
    await expectAccessible(page, `/new?project= (${theme})`);

    await page.goto(`/runs/${runId}`);
    await expect(page.getByRole("list", { name: "Steps" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Review the report" })).toBeVisible({
      timeout: 90_000,
    });
    await expectAccessible(page, `/runs/:id (${theme})`);

    await page.goto(`/runs/${runId}/review`);
    await expect(page.frameLocator('iframe[title="Report"]').locator("h1")).toBeVisible();
    await expect(page.getByRole("list", { name: "Claims" })).toBeVisible();
    await expectAccessible(page, `/runs/:id/review (${theme})`);

    await page.goto("/settings");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page, `/settings (${theme})`);

    await page.goto("/no/such/page");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expectAccessible(page, `not found (${theme})`);
  });
}

// CRL-71: the states a click, a live run or a narrow window reach, which the screens above do not.
for (const theme of ["light", "dark"] as const) {
  test(`the review's tabs, dialogs and menu pass axe in the ${theme} theme`, async ({
    page,
    request,
  }) => {
    await chooseTheme(page, theme);
    const { run_id: runId } = await completedRun(request, `Review dialogs ${theme}`);
    await page.goto(`/runs/${runId}/review`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.frameLocator('iframe[title="Report"]').locator("h1")).toBeVisible();
    await expect(page.getByRole("list", { name: "Claims" })).toBeVisible();
    await page.getByRole("list", { name: "Claims" }).getByRole("button").first().click();
    await expect(
      page
        .getByRole("list", { name: /^Evidence for / })
        .locator("mark")
        .first(),
    ).toBeVisible();
    await expectAccessible(page, `the Claims tab with a quoted passage (${theme})`);

    await page.getByRole("tab", { name: "Standards" }).click();
    await expect(page.getByRole("tabpanel").locator(".rule").first()).toBeVisible();
    await expectAccessible(page, `the Standards tab (${theme})`);
    await page.getByRole("tab", { name: "Process" }).click();
    await expect(page.getByRole("table", { name: "Stage timeline" })).toBeVisible();
    await expectAccessible(page, `the Process tab (${theme})`);
    await page.getByRole("tab", { name: "Sources" }).click();
    await expect(page.getByRole("table", { name: "Sources" })).toContainText("port.txt");
    await expectAccessible(page, `the Sources tab (${theme})`);

    await page.getByRole("button", { name: "Download" }).click();
    await expect(page.getByRole("menu", { name: "Download" }).getByRole("menuitem")).toHaveCount(4);
    await expect(page.getByRole("menuitem").first()).toBeFocused();
    await expectAccessible(page, `the open Download menu (${theme})`);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu", { name: "Download" })).toBeHidden();

    await page.getByRole("button", { name: "Return with note…" }).click();
    const back = page.getByRole("dialog", { name: "Return the report to the writer" });
    await expect(back.getByRole("textbox", { name: "Note for the writer" })).toBeFocused();
    await expectAccessible(page, `the Return dialog (${theme})`);
    await back.getByRole("button", { name: "Cancel" }).click();
    await expect(back).toBeHidden();

    await page.getByRole("button", { name: "Help", exact: true }).click();
    const help = page.getByRole("dialog", { name: "Help" });
    await expect(help.getByRole("heading", { name: "Help" })).toBeFocused();
    await expectAccessible(page, `the Help dialog (${theme})`);
    await help.getByRole("button", { name: "Close" }).click();
    await expect(help).toBeHidden();
  });

  test(`a run while writing, a stopped run and the narrow sidebar pass axe in the ${theme} theme`, async ({
    page,
    request,
  }) => {
    await chooseTheme(page, theme);
    const held = await completedRun(request, `Writing ${theme}`);
    const stopped = await stoppedRun(request, `Stopped ${theme}`);

    await holdWriting(page, held);
    await page.goto(`/runs/${held["run_id"]}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("heading", { name: "Writing the report" })).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Steps" }).locator('[aria-current="step"]'),
    ).toHaveCount(1);
    await expect(projectLink(page, held["project_id"] as string)).toHaveAccessibleName(/ writing$/);
    await expectAccessible(page, `/runs/:id while writing (${theme})`);

    await page.getByRole("button", { name: "Stop writing…" }).click();
    const stop = page.getByRole("dialog", { name: "Stop this report?" });
    await expect(stop.getByRole("button", { name: "Keep going" })).toBeFocused();
    await expectAccessible(page, `the Stop dialog (${theme})`);
    await stop.getByRole("button", { name: "Keep going" }).click();
    await expect(stop).toBeHidden();
    await page.unrouteAll();

    await page.goto(`/runs/${stopped.runId}`);
    await expect(
      page.getByRole("heading", { name: "Stopped before the report was written." }),
    ).toBeVisible();
    await expect(page.getByRole("region", { name: "Outcome" })).toBeVisible();
    await expectAccessible(page, `a stopped run's outcome (${theme})`);

    await page.setViewportSize({ width: 600, height: 800 });
    await page.goto(`/new?project=${stopped.projectId}`);
    await expect(page.getByText("port.txt").first()).toBeVisible();
    await page.getByRole("button", { name: "Your projects" }).click();
    await expect(page.getByRole("link", { name: "+ New report" })).toBeFocused();
    await expect(projectLink(page, stopped.projectId)).toBeVisible();
    await expectAccessible(page, `the sidebar overlay at 600 px (${theme})`);
  });
}
