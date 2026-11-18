import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RUN_PAGE } from "../../api/projects";
import type { RunSummary } from "../../api/types";
import { deferred } from "../../test/deferred";
import { packs, project, runSummary } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { WAITING_FOR_REVIEW } from "../../lib/words";
import { server } from "../../test/server";

// The page mounts the run options, which read the packs.
beforeEach(() => server.use(http.get("*/api/packs", () => HttpResponse.json(packs))));

function serveRuns(runs: RunSummary[] | Response) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    runs instanceof Response
      ? http.get("*/api/runs", () => runs)
      : http.get("*/api/runs", () => HttpResponse.json({ runs, next_before: null })),
  );
}

function many(n: number): RunSummary[] {
  return Array.from({ length: n }, (_, i) => ({
    ...runSummary,
    run_id: `${String(i).padStart(8, "0")}-0000-0000-0000-000000000000`,
    value_statement: `Statement ${i}`,
  }));
}

const cursorOf = (run: RunSummary) => `${run.created_at}|${run.run_id}`;

/** The API's keyset paging over `all` (newest first): each request answers the runs after its
 * `before` cursor and the cursor of its last run while more remain. Records each `before`. */
function servePaged(all: RunSummary[], options: { failOnce?: string } = {}) {
  const asked: string[] = [];
  let failed = false;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const before = params.get("before");
      asked.push(`${params.get("limit")}:${before ?? "-"}`);
      if (before !== null && before === options.failOnce && !failed) {
        failed = true;
        return HttpResponse.json(
          { detail: "the database is unavailable: connection reset" },
          { status: 503 },
        );
      }
      const start = before === null ? 0 : all.findIndex((r) => cursorOf(r) === before) + 1;
      const runs = all.slice(start, start + Number(params.get("limit")));
      const more = start + runs.length < all.length;
      return HttpResponse.json({ runs, next_before: more ? cursorOf(runs.at(-1)!) : null });
    }),
  );
  return asked;
}

it("lists the project's reports with links to progress or review", async () => {
  const running = {
    ...runSummary,
    run_id: "66666666-6666-6666-6666-666666666666",
    state: "drafting" as const,
    status: null,
    finished_at: null,
  };
  serveRuns([running, runSummary]);
  renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("list", { name: "Reports" });
  const rows = within(table).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]!).getByRole("link", { name: "Progress" })).toHaveAttribute(
    "href",
    `/runs/${running.run_id}`,
  );
  expect(within(rows[1]!).getByRole("link", { name: "Review" })).toHaveAttribute(
    "href",
    `/runs/${runSummary.run_id}/review`,
  );
  expect(within(rows[1]!).getByText(WAITING_FOR_REVIEW)).toBeInTheDocument();
  expect(within(rows[0]!).getByText("writing")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});

it("links a failed run to its outcome", async () => {
  const failed = {
    ...runSummary,
    run_id: "77777777-7777-7777-7777-777777777777",
    state: "failed" as const,
  };
  serveRuns([failed]);
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("link", { name: "Outcome" })).toHaveAttribute(
    "href",
    `/runs/${failed.run_id}`,
  );
});

it("shows an error when the run list fails", async () => {
  serveRuns(HttpResponse.json({ detail: "runs unavailable" }, { status: 400 }));
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("runs unavailable");
  expect(screen.queryByRole("list", { name: "Reports" })).not.toBeInTheDocument();
});

it("pages fifty at a time by cursor and stops at the last page", async () => {
  const all = many(120);
  const asked = servePaged(all);
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("list", { name: "Reports" });
  expect(within(table).getAllByRole("listitem")).toHaveLength(RUN_PAGE);
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(100));
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(120));
  expect(asked).toEqual([`50:-`, `50:${cursorOf(all[49]!)}`, `50:${cursorOf(all[99]!)}`]);
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  const values = [...table.querySelectorAll(".statement")];
  expect(new Set(values.map((c) => c.textContent)).size).toBe(120); // no run twice
});

it("keeps Show more in place, disabled, while the next page loads", async () => {
  const nextPage = deferred();
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", async ({ request }) => {
      const before = new URL(request.url).searchParams.get("before");
      if (before !== null) await nextPage.promise;
      const runs = many(100).slice(before === null ? 0 : 50, before === null ? 50 : 100);
      return HttpResponse.json({ runs, next_before: before === null ? "c1" : "c2" });
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("list", { name: "Reports" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  expect(screen.getByRole("button", { name: "Show more" })).toBeDisabled();
  nextPage.resolve();
  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(100));
  await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
});

it("pages past 500 runs to the oldest, with no ceiling", async () => {
  servePaged(many(520));
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("list", { name: "Reports" });
  const rows = () => table.querySelectorAll("li").length; // 520 rows: skip role queries
  for (let shown = RUN_PAGE; shown < 520; shown += RUN_PAGE) {
    await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(rows()).toBe(Math.min(shown + RUN_PAGE, 520)));
  }
  expect(table.querySelector("li:last-child")).toHaveTextContent("Statement 519");
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Showing the newest/)).not.toBeInTheDocument();
});

it("keeps the rows when the next page fails, and Show more tries again", async () => {
  const all = many(80);
  servePaged(all, { failOnce: cursorOf(all[49]!) });
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("list", { name: "Reports" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "the database is unavailable: connection reset",
  );
  expect(within(table).getAllByRole("listitem")).toHaveLength(RUN_PAGE);
  await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(80));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("starts each project's run list at the first page again", async () => {
  const other = { ...project, id: "99999999-9999-9999-9999-999999999999", name: "Danube" };
  const asked: string[] = [];
  const errors = vi.spyOn(console, "error");
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project, other])),
    http.get("*/api/projects/:id/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const before = params.get("before");
      asked.push(`${params.get("project_id")}:${before ?? "-"}`);
      const runs = many(100).slice(before === null ? 0 : 50, before === null ? 50 : 100);
      return HttpResponse.json({ runs, next_before: before === null ? "page-2" : null });
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  await screen.findByRole("list", { name: "Reports" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(asked).toContain(`${project.id}:page-2`));
  const sidebar = screen.getByRole("navigation", { name: "Your projects" });
  await user.click(within(sidebar).getByRole("link", { name: /^Danube/ }));
  await waitFor(() => expect(asked).toContain(`${other.id}:-`));
  expect(asked).not.toContain(`${other.id}:page-2`); // the next page did not carry over
  // siblings with one key kept the old value statement on screen after a switch
  expect(screen.getAllByRole("region", { name: "Value statement" })).toHaveLength(1);
  expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
  errors.mockRestore();
});

it("says when each report was written, its status in words and symbol, and its decision", async () => {
  const at = new Date(Date.now() - 3 * 3_600_000).toISOString();
  serveRuns([
    {
      ...runSummary,
      run_id: "a1111111-0000-0000-0000-000000000000",
      created_at: at,
      review_decision: "accepted",
    },
    {
      ...runSummary,
      run_id: "a2222222-0000-0000-0000-000000000000",
      created_at: at,
      review_decision: "returned",
    },
    {
      ...runSummary,
      run_id: "a3333333-0000-0000-0000-000000000000",
      created_at: at,
      review_decision: "returned",
      review_child_state: "cancelled",
    },
    {
      ...runSummary,
      run_id: "a4444444-0000-0000-0000-000000000000",
      created_at: at,
      state: "gate_rejected",
    },
  ]);
  renderApp(`/new?project=${project.id}`);
  const rows = within(await screen.findByRole("list", { name: "Reports" })).getAllByRole(
    "listitem",
  );
  expect(rows.map((r) => r.querySelector(".status")!.textContent)).toEqual([
    "✓ accepted",
    "↺ returned",
    `● ${WAITING_FOR_REVIEW}`, // its revision was stopped: waiting for review again (R-M15-1)
    "⚠ not supported by the sources",
  ]);
  const when = within(rows[0]!).getByText("3 hours ago");
  expect(when).toHaveAttribute("title", new Date(at).toLocaleString());
  expect(when.tagName).toBe("TIME");
});

it("offers each report's statement for the next one (CRL-84)", async () => {
  const [newer, older] = many(2);
  serveRuns([newer!, older!]);
  const { user, router } = renderApp(`/new?project=${project.id}`);
  const rows = within(await screen.findByRole("list", { name: "Reports" })).getAllByRole(
    "listitem",
  );
  const box = screen.getByRole("textbox", { name: "Value statement" });
  await user.type(box, "draft");
  const use = within(rows[1]!).getByRole("button", { name: "Use this statement" });
  expect(use).toHaveAccessibleDescription("Statement 1"); // which one, out of the row's context
  await user.click(use);
  expect(box).toHaveValue("Statement 1");
  expect(box).toHaveFocus(); // the analyst sees what changed, far above the list
  expect(router.state.location.search).toBe(`?project=${project.id}`); // the sources stay
});

it("marks a revised report, and keeps its statement alone as the button's description (CRL-102)", async () => {
  const revised: RunSummary = {
    ...runSummary,
    run_id: "33333333-3333-3333-3333-333333333334",
    parent_run_id: runSummary.run_id,
  };
  serveRuns([revised, runSummary]);
  renderApp(`/new?project=${project.id}`);
  const list = await screen.findByRole("list", { name: "Reports" });
  const [first, second] = within(list).getAllByRole("listitem");
  expect(first).toHaveTextContent("Revised report");
  expect(second).not.toHaveTextContent("Revised report");
  expect(
    within(first!).getByRole("button", { name: "Use this statement" }),
  ).toHaveAccessibleDescription(runSummary.value_statement);
});

it("clamps a long statement to two lines, keeps it whole in the title and in Use this statement (CRL-110)", async () => {
  const long = `${"A very long value statement. ".repeat(140)}end`;
  serveRuns([{ ...runSummary, value_statement: long }]);
  const { user } = renderApp(`/new?project=${project.id}`);
  const [row] = within(await screen.findByRole("list", { name: "Reports" })).getAllByRole(
    "listitem",
  );
  const statement = row!.querySelector(".statement")!;
  expect(statement).toHaveClass("clamped");
  expect(statement).toHaveAttribute("title", long);
  const box = screen.getByRole("textbox", { name: "Value statement" });
  await user.click(within(row!).getByRole("button", { name: "Use this statement" }));
  expect(box).toHaveValue(long);
});
