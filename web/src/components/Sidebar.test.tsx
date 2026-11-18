import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { PROJECTS_POLL_MS } from "../api/projects";
import type { ProjectView } from "../api/types";
import { noRuns, packs, project, RUN_ID, runProgress } from "../test/fixtures";
import { projectsRefetchInterval } from "../test/poll";
import { renderApp } from "../test/render";
import { server } from "../test/server";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

/** Pins the clock to `hours:minutes` local time today (CRL-78). The sidebar groups by calendar
 * day, so on the real clock just after midnight a project minutes old falls on yesterday. Only
 * Date is faked: timers stay real for user-event and waitFor. Call it before building data. */
function at(hours: number, minutes: number) {
  const now = new Date();
  now.setHours(hours, minutes, 0, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
}

afterEach(() => {
  vi.useRealTimers();
});

let made = 0;
function named(name: string, overrides: Partial<ProjectView> = {}): ProjectView {
  made += 1;
  return {
    ...project,
    id: `${String(made).padStart(8, "0")}-1111-1111-1111-111111111111`,
    name,
    ...overrides,
  };
}

function serve(list: ProjectView[]) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json(list)),
    http.get("*/api/projects/:id/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
}

const sidebar = () => screen.getByRole("navigation", { name: "Your projects" });

it("groups the projects by their last activity, newest first, each with one status", async () => {
  at(12, 0);
  serve([
    named("old", { last_activity_at: hoursAgo(24 * 30) }),
    named("week", { last_activity_at: hoursAgo(48), reports_to_review: 2 }),
    named("now", { last_activity_at: hoursAgo(0.1), reports_writing: 1 }),
    named("later", { last_activity_at: hoursAgo(0.2) }),
  ]);
  renderApp("/new");
  const today = await within(sidebar()).findByRole("region", { name: "Today" });
  expect(
    within(today)
      .getAllByRole("link")
      .map((a) => a.textContent),
  ).toEqual(["now… writing", "laterno reports yet"]);
  expect(within(sidebar()).getByRole("region", { name: "This week" })).toHaveTextContent(
    "week● 2 waiting for review",
  );
  expect(within(sidebar()).getByRole("region", { name: "Earlier" })).toHaveTextContent("old");
  expect(within(sidebar()).getByRole("link", { name: /^now/ }).getAttribute("href")).toMatch(
    /^\/new\?project=\d{8}-/,
  );
  expect(within(sidebar()).getByRole("link", { name: "+ New report" })).toHaveAttribute(
    "href",
    "/new",
  );
});

it("groups by calendar day just after midnight: minutes ago can be yesterday (CRL-78)", async () => {
  at(0, 5);
  serve([
    named("tonight", { last_activity_at: hoursAgo(4 / 60) }),
    named("last night", { last_activity_at: hoursAgo(10 / 60) }),
  ]);
  renderApp("/new");
  const today = await within(sidebar()).findByRole("region", { name: "Today" });
  expect(
    within(today)
      .getAllByRole("link")
      .map((a) => a.textContent),
  ).toEqual(["tonightno reports yet"]);
  expect(within(sidebar()).getByRole("region", { name: "This week" })).toHaveTextContent(
    "last night",
  );
});

it("says where the projects will appear, and searches from 16 projects on", async () => {
  serve([]);
  renderApp("/new");
  expect(await screen.findByText("Your projects will appear here.")).toBeInTheDocument();
  cleanup();
  const fifteen = Array.from({ length: 15 }, (_, i) => named(`p${i}`));
  serve(fifteen);
  renderApp("/new");
  await waitFor(() => expect(within(sidebar()).getAllByRole("listitem")).toHaveLength(15));
  expect(screen.queryByRole("searchbox", { name: "Search your projects" })).toBeNull();
  cleanup();
  serve([...fifteen, named("Danube")]);
  const { user } = renderApp("/new");
  await user.type(await screen.findByRole("searchbox", { name: "Search your projects" }), "DANU");
  expect(within(sidebar()).getAllByRole("listitem")).toHaveLength(1);
  expect(within(sidebar()).getByRole("link", { name: /^Danube/ })).toBeInTheDocument();
});

it("marks the project page's row and a run's project as the current page", async () => {
  const other = named("other");
  serve([project, other]);
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress())));
  const { router } = renderApp(`/new?project=${project.id}`);
  const row = await within(sidebar()).findByRole("link", { name: /^Black Sea/ });
  await waitFor(() => expect(row).toHaveAttribute("aria-current", "page"));
  expect(within(sidebar()).getByRole("link", { name: /^other/ })).not.toHaveAttribute(
    "aria-current",
  );
  await router.navigate(`/runs/${RUN_ID}`);
  await waitFor(() =>
    expect(within(sidebar()).getByRole("link", { name: /^Black Sea/ })).toHaveAttribute(
      "aria-current",
      "page",
    ),
  );
  await router.navigate("/new");
  await waitFor(() =>
    expect(within(sidebar()).getByRole("link", { name: /^Black Sea/ })).not.toHaveAttribute(
      "aria-current",
    ),
  );
});

it("reads the list again on the fallback poll while a report is being written, and not otherwise", async () => {
  let writing = 1;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([{ ...project, reports_writing: writing }])),
  );
  const { queryClient } = renderApp("/new");
  await within(sidebar()).findByText("writing");
  expect(projectsRefetchInterval(queryClient)).toBe(PROJECTS_POLL_MS);
  writing = 0;
  await queryClient.refetchQueries({ queryKey: ["projects"], exact: true });
  await within(sidebar()).findByText("no reports yet");
  expect(projectsRefetchInterval(queryClient)).toBe(false);
});

it("names a project's link by its visible text, the project then its status", async () => {
  // WCAG 2.5.3 (axe label-content-name-mismatch): the name holds all the visible text, so a
  // speech user can say what they see; the status symbol stays out (aria-hidden).
  serve([named("Danube", { reports_to_review: 2 })]);
  renderApp("/new");
  const link = await within(sidebar()).findByRole("link", { name: /^Danube/ });
  expect(link).toHaveAccessibleName("Danube 2 waiting for review");
  expect(link).not.toHaveAttribute("aria-describedby");
});

it("shows a project-list failure in the sidebar", async () => {
  server.use(
    http.get("*/api/projects", () =>
      HttpResponse.json({ detail: "database offline" }, { status: 400 }),
    ),
  );
  renderApp("/new");
  expect(await within(sidebar()).findByRole("alert")).toHaveTextContent("database offline");
});

it("puts the version at the sidebar's foot, outside the navigation, and shows nothing before it loads", async () => {
  serve([]);
  renderApp("/new");
  expect(screen.queryByText(/^Corelata \d/)).toBeNull();
  const foot = await screen.findByText("Corelata 0.1.0");
  expect(foot).not.toBeEmptyDOMElement();
  expect(sidebar()).not.toContainElement(foot);
  expect(foot.parentElement).toBe(sidebar().parentElement);
  // in a landmark of its own, so all the page's content sits in one (axe's `region`, CRL-50)
  expect(screen.getByRole("contentinfo", { name: "Version" })).toBe(foot);
});
