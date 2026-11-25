import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import type { SourceView } from "../../api/types";
import { deferred } from "../../test/deferred";
import { nodeFormData, NodeFileClass } from "../../test/node-web";
import {
  candidates,
  DISCOVERY_ID,
  discoveryView,
  info,
  noRuns,
  packs,
  project,
  RUN_ID,
  runProgress,
  runSummary,
  runTrace,
  sources,
} from "../../test/fixtures";
import { expectNoEngineWords, visiblePrimaryButtons } from "../../test/engine-words";
import { GUIDANCE_MAX_LENGTH, VALUE_STATEMENT_MAX_LENGTH } from "../../lib/limits";
import { decodeSelection, SELECTION_PARAM, sourceToken } from "../../lib/selection";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

const inSidebar = () => within(screen.getByRole("navigation", { name: "Your projects" }));

function serve() {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(sources)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
}

it("starts a run with the chosen sources, statement, profile and iterations, then opens its progress", async () => {
  serve();
  let body: unknown;
  server.use(
    http.post("*/api/runs", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    // the progress screen it opens reads the run
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  const start = await screen.findByRole("button", { name: "Write the report" });
  expect(start).toBeDisabled(); // no statement yet
  await user.type(
    screen.getByRole("textbox", { name: "Value statement" }),
    "Varna matters to shippers",
  );
  await user.click(
    screen.getByRole("checkbox", { name: "Use letter.coglossa.json in this report" }),
  );
  const profile = screen.getByRole("combobox", { name: "Team profile" });
  expect(screen.getByRole("option", { name: "draft-west (draft)" })).toBeDisabled();
  await user.selectOptions(profile, "team-east");
  await user.clear(screen.getByRole("spinbutton", { name: "Revision rounds" }));
  await user.type(screen.getByRole("spinbutton", { name: "Revision rounds" }), "1");
  await user.type(
    screen.getByRole("textbox", { name: "Guidance for the writer" }),
    "Lead with capacity",
  );
  await user.click(start);
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body).toEqual({
    project_id: project.id,
    source_ids: [sources[0]!.id],
    value_statement: "Varna matters to shippers",
    profile: "team-east",
    max_iterations: 1,
    extra_guidance: "Lead with capacity",
    kind: "report",
  });
});

it("labels the deployment's default profile, sends profile null when left, and shows a rejected start inline", async () => {
  serve();
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({ ...info, default_profile: "team-east" }),
    ),
    http.post("*/api/runs", async ({ request }) => {
      expect(((await request.json()) as { profile: unknown }).profile).toBeNull();
      return HttpResponse.json(
        { detail: "profile 'team-east' is a draft (draft: true)" },
        { status: 422 },
      );
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const profile = await screen.findByRole("combobox", { name: "Team profile" });
  expect(await screen.findByRole("option", { name: "Default (team-east)" })).toHaveValue("");
  expect(profile).toHaveValue("");
  await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("is a draft");
});

it("starts Revision rounds from the deployment's configured rounds and sends them untouched (CRL-67)", async () => {
  serve();
  let body: { max_iterations?: unknown } = {};
  server.use(
    http.get("*/api/system/info", () => HttpResponse.json({ ...info, max_iterations: 1 })),
    http.post("*/api/runs", async ({ request }) => {
      body = (await request.json()) as typeof body;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  await waitFor(() =>
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(1),
  );
  await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body.max_iterations).toBe(1);
});

it("leaves the rounds to the deployment when its info cannot be read (CRL-67)", async () => {
  serve();
  let body: { max_iterations?: unknown } = {};
  server.use(
    http.get("*/api/system/info", () => HttpResponse.json({ detail: "down" }, { status: 500 })),
    http.post("*/api/runs", async ({ request }) => {
      body = (await request.json()) as typeof body;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body.max_iterations).toBeNull();
});

it("an emptied Revision rounds follows the deployment's rounds, not 0 (CRL-90)", async () => {
  serve();
  let body: { max_iterations?: unknown } = {};
  server.use(
    http.get("*/api/system/info", () => HttpResponse.json({ ...info, max_iterations: 3 })),
    http.post("*/api/runs", async ({ request }) => {
      body = (await request.json()) as typeof body;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  const rounds = await screen.findByRole("spinbutton", { name: "Revision rounds" });
  await waitFor(() => expect(rounds).toHaveValue(3));
  await user.clear(rounds);
  await user.type(rounds, "1");
  await user.clear(rounds); // retyping, then thought better of it
  await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
  expect(rounds).toHaveValue(3); // left: the deployment's rounds again
  // the draft follows the deployment (null), as a field never touched does
  expect(JSON.parse(sessionStorage.getItem(`corelata.draft.${project.id}`) ?? "{}")).toEqual(
    expect.objectContaining({ maxIterations: null }),
  );
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body.max_iterations).toBe(3); // the deployment's, sent as for an untouched field (CRL-67)
});

it("cannot start without a selected source", async () => {
  serve();
  const { user } = renderApp(`/new?project=${project.id}`);
  await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
  for (const name of ["Use port.txt in this report", "Use letter.coglossa.json in this report"]) {
    await user.click(screen.getByRole("checkbox", { name }));
  }
  expect(screen.getByRole("button", { name: "Write the report" })).toBeDisabled();
  expect(screen.getByText("Choose at least one source.")).toBeInTheDocument();
});

const OTHER = { ...project, id: "66666666-6666-6666-6666-666666666666", name: "Baltic" };

function serveTwoProjects() {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project, OTHER])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(sources)),
    http.get(`*/api/projects/${OTHER.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
}

/** The sources the URL's `pick` chooses, out of `ids` (the project's), joined with ",". */
function chosenIn(search: string, ids = sources.map((s) => s.id)): string | null {
  const picked = new URLSearchParams(search).get(SELECTION_PARAM);
  return picked === null ? null : [...decodeSelection(picked, ids)].join(",");
}

const [PORT, LETTER] = sources as [SourceView, SourceView];
const GONE = "99999999-9999-9999-9999-999999999999"; // not a source of the project (any more)

it("keeps the chosen sources in the URL, so a reload selects them again (R-M17-6)", async () => {
  serve();
  server.use(
    http.post("*/api/discoveries", () => HttpResponse.json(discoveryView(), { status: 202 })),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const first = renderApp(`/new?project=${project.id}`);
  const letter = await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
  expect(letter).toBeChecked(); // no parameter: every source
  expect(chosenIn(first.router.state.location.search)).toBeNull();
  await first.user.click(letter);
  await waitFor(() => expect(chosenIn(first.router.state.location.search)).toBe(PORT.id));
  expect(first.router.state.historyAction).toBe("REPLACE");
  // a discovery keeps the choice beside it, and the choice keeps the discovery
  await first.user.click(screen.getByRole("button", { name: "Suggest value" }));
  await waitFor(() =>
    expect(new URLSearchParams(first.router.state.location.search).get("discovery")).toBe(
      DISCOVERY_ID,
    ),
  );
  expect(chosenIn(first.router.state.location.search)).toBe(PORT.id);
  const url = `/new${first.router.state.location.search}`;
  cleanup(); // the reload

  renderApp(url);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
  ).not.toBeChecked();
  expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
    "1 of 2 selected",
  );
  expect(
    await screen.findByRole("list", { name: "Suggested value statements" }),
  ).toBeInTheDocument();
});

it("drops ids in the URL that are not the project's, and starts with the rest", async () => {
  serve();
  let body: { source_ids?: string[] } = {};
  server.use(
    http.post("*/api/runs", async ({ request }) => {
      body = (await request.json()) as typeof body;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}&sources=${GONE},${PORT.id}`);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
  ).not.toBeChecked();
  expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
    "1 of 2 selected",
  );
  await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body.source_ids).toEqual([PORT.id]); // the stale id is not sent
});

it("a URL that names none of the project's sources selects none", async () => {
  serve();
  renderApp(`/new?project=${project.id}&sources=${GONE}`);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Write the report" })).toBeDisabled();
  expect(screen.getByText("Choose at least one source.")).toBeInTheDocument();
});

it("an old sources= link loads, and the next choice rewrites it in the short form (CRL-54)", async () => {
  serve();
  const { router, user } = renderApp(`/new?project=${project.id}&sources=${PORT.id}`);
  const letter = await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
  expect(letter).not.toBeChecked();
  await user.click(letter);
  await waitFor(() =>
    expect(chosenIn(router.state.location.search)).toBe(`${PORT.id},${LETTER.id}`),
  );
  const params = new URLSearchParams(router.state.location.search);
  expect(params.get("sources")).toBeNull();
  expect(params.get(SELECTION_PARAM)).toBe("x"); // every source: none left out
  expect(router.state.location.search).not.toContain(PORT.id);
});

it("choosing another project drops the discovery and the chosen sources from the URL (R-M16-14, R-M17-6)", async () => {
  serveTwoProjects();
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const { router, user } = renderApp(
    `/new?project=${project.id}&sources=${PORT.id}&discovery=${DISCOVERY_ID}`,
  );
  await screen.findByRole("list", { name: "Suggested value statements" });
  await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
  await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
  expect(
    screen.queryByRole("list", { name: "Suggested value statements" }),
  ).not.toBeInTheDocument();
});

it("a discovery that starts for the old project does not write itself into the new project's URL", async () => {
  serveTwoProjects();
  const held = deferred();
  let posted = false;
  let answered = false;
  server.use(
    http.post("*/api/discoveries", async () => {
      posted = true;
      await held.promise;
      answered = true;
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
  );
  const { router, user, queryClient } = renderApp(`/new?project=${project.id}`);
  await user.click(await screen.findByRole("button", { name: "Suggest value" }));
  await waitFor(() => expect(posted).toBe(true));
  await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
  await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
  held.resolve();
  // the answer arrived and the mutation settled: whatever it would write, it has written
  await waitFor(() => expect(answered).toBe(true));
  await waitFor(() => expect(queryClient.isMutating()).toBe(0));
  expect(router.state.location.search).toBe(`?project=${OTHER.id}`);
});

it("New report without a project asks which project, and names the tab (M18 spec §5.1, §3.4)", async () => {
  serve();
  renderApp("/new");
  expect(await screen.findByRole("heading", { name: "New report" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Which project is it for?" })).toBeInTheDocument();
  expect(await screen.findByRole("combobox", { name: "Project" })).toHaveValue("");
  expect(document.title).toBe("New report – Corelata");
  expect(screen.queryByRole("region", { name: "Sources" })).toBeNull();
  expectNoEngineWords(screen.getByRole("main"));
});

it("a project that does not exist says so instead of showing its form, and names the tab (CRL-130)", async () => {
  serve();
  const unknown = "99999999-9999-9999-9999-999999999999";
  server.use(
    http.get(`*/api/projects/${unknown}/sources`, () =>
      HttpResponse.json({ detail: `project ${unknown} not found` }, { status: 404 }),
    ),
  );
  renderApp(`/new?project=${unknown}`);
  const main = screen.getByRole("main");
  expect(
    await within(main).findByRole("heading", { name: "Project not found" }),
  ).toBeInTheDocument();
  expect(within(main).getByText(/does not exist, or it was deleted/)).toBeInTheDocument();
  expect(within(main).getByRole("link", { name: "Choose a project" })).toHaveAttribute(
    "href",
    "/new",
  );
  expect(within(main).queryByRole("button", { name: "Write the report" })).toBeNull();
  expect(within(main).queryByRole("textbox", { name: "Value statement" })).toBeNull();
  expect(within(main).queryByRole("region", { name: "Sources" })).toBeNull();
  expect(within(main).queryByRole("alert")).toBeNull();
  await waitFor(() => expect(document.title).toBe("Project not found – Corelata"));
});

it("keeps the project's form when its sources cannot be read for another reason (CRL-130)", async () => {
  serve();
  server.use(
    http.get(`*/api/projects/${project.id}/sources`, () =>
      HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 }),
    ),
  );
  renderApp(`/new?project=${project.id}`);
  const main = screen.getByRole("main");
  expect(await within(main).findByRole("alert")).toHaveTextContent("the database is unavailable");
  expect(within(main).getByRole("heading", { name: project.name })).toBeInTheDocument();
  expect(within(main).getByRole("button", { name: "Write the report" })).toBeInTheDocument();
  expect(within(main).queryByRole("heading", { name: "Project not found" })).toBeNull();
});

it("the project page names the project, has no picker, folds the options and has one primary button", async () => {
  serve();
  renderApp(`/new?project=${project.id}`);
  const main = screen.getByRole("main");
  expect(await within(main).findByRole("heading", { name: project.name })).toBeInTheDocument();
  expect(within(main).getByText("Project")).toHaveClass("eyebrow");
  expect(within(main).queryByRole("combobox", { name: "Project" })).toBeNull();
  await waitFor(() => expect(document.title).toBe(`${project.name} – Corelata`));
  const options = within(main).getByText("More options").closest("details")!;
  expect(options).not.toHaveAttribute("open");
  expect(within(options).getByRole("combobox", { name: "Team profile" })).toBeInTheDocument();
  expect(within(options).getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(2);
  expect(visiblePrimaryButtons(main)).toHaveLength(1);
  expect(within(main).getByRole("button", { name: "Write the report" })).toHaveClass("primary");
});

it("shows no engine word on the project page, with sources, suggestions and reports (M18 spec §4)", async () => {
  serve();
  server.use(
    http.get("*/api/runs", () =>
      HttpResponse.json({
        runs: [
          { ...runSummary, run_id: "a0000000-0000-0000-0000-000000000000", state: "drafting" },
          { ...runSummary, review_decision: "returned", review_child_state: "failed" },
        ],
        next_before: null,
      }),
    ),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(
        discoveryView({
          state: "completed",
          candidates: [{ ...candidates[0]!, confidence_note: "Stated directly." }],
        }),
      ),
    ),
  );
  renderApp(`/new?project=${project.id}&discovery=${DISCOVERY_ID}`);
  const main = screen.getByRole("main");
  await within(main).findByRole("list", { name: "Suggested value statements" });
  await within(main).findByRole("list", { name: "Reports" });
  expect(within(main).getByText(/· 2 passages$/)).toBeInTheDocument();
  expectNoEngineWords(main);
});

describe("adding sources from the project page", () => {
  beforeEach(async () => {
    vi.stubGlobal("FormData", await nodeFormData());
    vi.stubGlobal("File", NodeFileClass);
  });

  /** The project's sources answer with what was uploaded so far. */
  function serveUploads(projectId: string, held?: Promise<void>) {
    const list: SourceView[] = [...sources];
    server.use(
      http.get(`*/api/projects/${projectId}/sources`, () => HttpResponse.json(list)),
      http.post(`*/api/projects/${projectId}/sources`, async ({ request }) => {
        const name = ((await request.formData()).get("file") as File).name;
        if (held) await held;
        const added = { ...sources[0]!, id: `id-${name}`, name, format: "md" };
        list.push(added);
        return HttpResponse.json([added], { status: 201 });
      }),
    );
  }

  it("keeps every file of a batch in the URL when the choice was narrowed (stale onAdded)", async () => {
    serveTwoProjects();
    serveUploads(project.id);
    const { router, user } = renderApp(`/new?project=${project.id}&sources=${PORT.id}`);
    await user.upload(await screen.findByLabelText("Choose files"), [
      new File(["a"], "a.md"),
      new File(["b"], "b.md"),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() =>
      expect(
        chosenIn(router.state.location.search, [...sources.map((s) => s.id), "id-a.md", "id-b.md"]),
      ).toBe(`${PORT.id},id-a.md,id-b.md`),
    );
    // The URL update lands after the sources refetch has rendered; wait for the checked state
    // rather than asserting once on the first box the query returns.
    expect(
      await screen.findByRole("checkbox", { name: "Use b.md in this report", checked: true }),
    ).toBeChecked();
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Use a.md in this report" })).toBeChecked(),
    );
    expect(
      screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
    ).not.toBeChecked();
  });

  /** Runs `body` with no render in between (React renders when the act scope ends): what a
   * click and an upload finishing in one frame do. */
  const inOneFrame = (body: () => Promise<void>) => act(body);
  /** Waits, inside such a frame, until `done` holds. */
  async function until(done: () => boolean) {
    for (let i = 0; i < 200 && !done(); i++) await new Promise((r) => setTimeout(r, 5));
    if (!done()) throw new Error("the race this test sets up never happened");
  }
  const ALL = [...sources.map((s) => s.id), "id-a.md"];

  it("a tick that lands just after an upload's write keeps the uploaded source (CRL-62)", async () => {
    serveTwoProjects();
    const held = deferred();
    serveUploads(project.id, held.promise);
    const { router, user, queryClient } = renderApp(
      `/new?project=${project.id}&sources=${PORT.id}`,
    );
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    const port = screen.getByRole("checkbox", { name: `Use ${PORT.name} in this report` });
    await inOneFrame(async () => {
      held.resolve();
      await until(() => router.state.location.search.includes(sourceToken("id-a.md")));
      fireEvent.click(port); // the page has not rendered the upload's write yet
    });
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(chosenIn(router.state.location.search, ALL)).toBe("id-a.md");
  });

  it("an upload's write that lands just after a tick keeps the tick (CRL-62)", async () => {
    serveTwoProjects();
    const held = deferred();
    serveUploads(project.id, held.promise);
    const { router, user, queryClient } = renderApp(
      `/new?project=${project.id}&sources=${PORT.id}`,
    );
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    const letter = screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
    await inOneFrame(async () => {
      fireEvent.click(letter);
      held.resolve(); // its write lands before the page renders the tick
      await until(() => queryClient.isMutating() === 0);
    });
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(chosenIn(router.state.location.search, ALL)).toBe(`${PORT.id},${LETTER.id},id-a.md`);
  });

  it("starting a discovery as an upload finishes keeps both the source and the discovery (CRL-62)", async () => {
    serveTwoProjects();
    const held = deferred();
    serveUploads(project.id, held.promise);
    server.use(
      http.post("*/api/discoveries", () => HttpResponse.json(discoveryView(), { status: 202 })),
      http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
        HttpResponse.json(discoveryView({ state: "completed", candidates })),
      ),
    );
    const { router, user, queryClient } = renderApp(
      `/new?project=${project.id}&sources=${PORT.id}`,
    );
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    const suggest = screen.getByRole("button", { name: "Suggest value" });
    await inOneFrame(async () => {
      fireEvent.click(suggest);
      held.resolve();
      await until(() => queryClient.isMutating() === 0);
    });
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    const search = new URLSearchParams(router.state.location.search);
    expect(search.get("discovery")).toBe(DISCOVERY_ID);
    expect(chosenIn(router.state.location.search, ALL)).toBe(`${PORT.id},id-a.md`);
  });

  it("an upload while the URL lists the sources left out keeps it as it is, the new one chosen (CRL-54)", async () => {
    serveTwoProjects();
    serveUploads(project.id);
    const search = `?project=${project.id}&pick=x.${sourceToken(LETTER.id)}`;
    const { router, user } = renderApp(`/new${search}`);
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(
      await screen.findByRole("checkbox", { name: "Use a.md in this report", checked: true }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
    ).not.toBeChecked();
    expect(router.state.location.search).toBe(search);
  });

  it("a source uploaded while the earlier run loads stays chosen once the run fills the form (CRL-84)", async () => {
    serveTwoProjects();
    serveUploads(project.id);
    const held = deferred();
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, async () => {
        await held.promise;
        return HttpResponse.json(runProgress({ source_ids: [LETTER.id] }));
      }),
    );
    const { router, user } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(
      await screen.findByRole("checkbox", { name: "Use a.md in this report", checked: true }),
    ).toBeChecked();
    held.resolve();
    await waitFor(() => expect(router.state.location.search).not.toContain("from="));
    expect(chosenIn(router.state.location.search, ALL)).toBe(`${LETTER.id},id-a.md`);
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
      ).not.toBeChecked(),
    );
    expect(screen.getByRole("checkbox", { name: "Use a.md in this report" })).toBeChecked();
  });

  it("drops the chosen files when another project is opened", async () => {
    serveTwoProjects();
    const { user } = renderApp(`/new?project=${project.id}`);
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    const chips = () => within(screen.getByRole("list", { name: "Chosen files" }));
    expect(chips().getAllByRole("listitem")).toHaveLength(1);
    await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
    await screen.findByRole("heading", { name: "Baltic" });
    expect(chips().queryAllByRole("listitem")).toHaveLength(0);
  });

  it("a batch in flight when another project is opened does not write to its URL", async () => {
    serveTwoProjects();
    const held = deferred();
    serveUploads(project.id, held.promise);
    const { router, user, queryClient } = renderApp(
      `/new?project=${project.id}&sources=${PORT.id}`,
    );
    await user.upload(await screen.findByLabelText("Choose files"), new File(["a"], "a.md"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
    held.resolve();
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    await new Promise((settle) => setTimeout(settle, 20));
    expect(router.state.location.search).toBe(`?project=${OTHER.id}`);
  });

  it("a Coglossa fetch in flight when another project is opened does not write to its URL", async () => {
    serveTwoProjects();
    const held = deferred();
    server.use(
      http.get(`*/api/projects/${OTHER.id}/sources`, () =>
        HttpResponse.json([{ ...LETTER, id: "id-baltic", name: "baltic.txt" }]),
      ),
      http.get("*/api/system/info", () => HttpResponse.json({ ...info, coglossa: true })),
      http.post(`*/api/projects/${project.id}/sources/from-coglossa`, async () => {
        await held.promise;
        return HttpResponse.json([{ ...PORT, id: "id-fetched", name: "fetched.json" }], {
          status: 201,
        });
      }),
    );
    const { router, user, queryClient } = renderApp(
      `/new?project=${project.id}&sources=${PORT.id}`,
    );
    await user.type(await screen.findByRole("textbox", { name: "Coglossa run id" }), "run-42");
    await user.click(screen.getByRole("button", { name: "Fetch from Coglossa" }));
    await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
    // a new project's form starts empty
    expect(screen.getByRole("textbox", { name: "Coglossa run id" })).toHaveValue("");
    // narrow the choice, so the URL carries the sources a late fetch could append to
    await user.click(
      await screen.findByRole("checkbox", { name: "Use baltic.txt in this report" }),
    );
    await waitFor(() => expect(chosenIn(router.state.location.search)).toBe(""));
    const before = router.state.location.search;
    held.resolve();
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    await new Promise((settle) => setTimeout(settle, 20));
    expect(router.state.location.search).toBe(before);
  });
});

it("says Starting… on the start button while the run is being created (CRL-43)", async () => {
  serve();
  const held = deferred();
  server.use(
    http.post("*/api/runs", async () => {
      await held.promise;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Write the report" }));
  expect(await screen.findByRole("button", { name: "Starting…" })).toBeDisabled();
  held.resolve();
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
});

describe("the draft (CRL-74)", () => {
  const key = `corelata.draft.${project.id}`;

  it("keeps the statement, profile and rounds across a reload", async () => {
    serve();
    const { user } = renderApp(`/new?project=${project.id}`);
    await user.type(
      await screen.findByRole("textbox", { name: "Value statement" }),
      "Varna matters to shippers",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Team profile" }), "team-east");
    await user.clear(screen.getByRole("spinbutton", { name: "Revision rounds" }));
    await user.type(screen.getByRole("spinbutton", { name: "Revision rounds" }), "1");
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toEqual({
        statement: "Varna matters to shippers",
        profile: "team-east",
        maxIterations: 1,
        guidance: "",
      }),
    );
    cleanup(); // the reload: a new page in the same tab
    renderApp(`/new?project=${project.id}`);
    expect(await screen.findByRole("textbox", { name: "Value statement" })).toHaveValue(
      "Varna matters to shippers",
    );
    // the profile shows once the pack's profiles are read
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("team-east"),
    );
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(1);
  });

  it("keeps the writer guidance across a reload, and loads a draft saved without it (CRL-132)", async () => {
    serve();
    sessionStorage.setItem(
      key,
      JSON.stringify({ statement: "Old", profile: null, maxIterations: null }),
    );
    const { user } = renderApp(`/new?project=${project.id}`);
    const guidance = await screen.findByRole("textbox", { name: "Guidance for the writer" });
    expect(guidance).toHaveValue("");
    await user.type(guidance, "Lead with capacity");
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toMatchObject({
        guidance: "Lead with capacity",
      }),
    );
    cleanup(); // the reload
    renderApp(`/new?project=${project.id}`);
    expect(await screen.findByRole("textbox", { name: "Guidance for the writer" })).toHaveValue(
      "Lead with capacity",
    );
  });

  it("clears the draft once the run starts", async () => {
    serve();
    server.use(
      http.post("*/api/runs", () => HttpResponse.json(runProgress(), { status: 202 })),
      http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
    );
    const { router, user } = renderApp(`/new?project=${project.id}`);
    await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
    await waitFor(() => expect(sessionStorage.getItem(key)).not.toBeNull());
    await user.click(screen.getByRole("button", { name: "Write the report" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`),
    );
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("keeps the draft when the start is refused", async () => {
    serve();
    server.use(http.post("*/api/runs", () => HttpResponse.json({ detail: "no" }, { status: 422 })));
    const { user } = renderApp(`/new?project=${project.id}`);
    await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
    await user.click(screen.getByRole("button", { name: "Write the report" }));
    await screen.findByRole("alert");
    expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toMatchObject({ statement: "x" });
  });

  it("never shows a draft in another project, and finds each project's own again", async () => {
    serveTwoProjects();
    const { router, user } = renderApp(`/new?project=${project.id}`);
    await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "Varna");
    await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
    const other = await screen.findByRole("textbox", { name: "Value statement" });
    expect(other).toHaveValue("");
    await user.type(other, "Riga");
    expect(JSON.parse(sessionStorage.getItem(`corelata.draft.${OTHER.id}`) ?? "null")).toEqual({
      statement: "Riga",
      profile: null,
      maxIterations: null,
      guidance: "",
    });
    await user.click(inSidebar().getByRole("link", { name: /^Black Sea/ }));
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${project.id}`));
    expect(await screen.findByRole("textbox", { name: "Value statement" })).toHaveValue("Varna");
  });

  it("a saved profile that was removed since goes back to the default once the packs load (CRL-108)", async () => {
    serve();
    sessionStorage.setItem(
      key,
      JSON.stringify({ statement: "Varna", profile: "retired", maxIterations: null }),
    );
    renderApp(`/new?project=${project.id}`);
    expect(
      await screen.findByText(
        "Team profile “retired” is no longer available, so no team profile is used.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue(""),
    );
    expect(screen.getByText("More options").closest("details")).toHaveAttribute("open");
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toEqual({
        statement: "Varna",
        profile: null,
        maxIterations: null,
        guidance: "",
      }),
    );
  });

  it("a saved statement over the limit holds Write until it is shortened (CRL-108)", async () => {
    serve();
    const long = "y".repeat(VALUE_STATEMENT_MAX_LENGTH + 1);
    sessionStorage.setItem(key, JSON.stringify({ statement: long, profile: null }));
    renderApp(`/new?project=${project.id}`);
    expect(await screen.findByRole("textbox", { name: "Value statement" })).toHaveValue(long);
    // the sources are chosen, so only the length holds Write
    expect(
      await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
    ).toBeChecked();
    expect(screen.getByText("Shorten the statement to write the report.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Write the report" })).toBeDisabled();
  });

  it("works without storage: a page that cannot save still takes the statement", async () => {
    serve();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { user } = renderApp(`/new?project=${project.id}`);
    const box = await screen.findByRole("textbox", { name: "Value statement" });
    await user.type(box, "x");
    expect(box).toHaveValue("x");
  });
});

describe("starting from an earlier run (CRL-84)", () => {
  const key = `corelata.draft.${project.id}`;
  const EARLIER = runProgress({
    state: "gate_rejected",
    value_statement: "Burgas matters to shippers",
    profile: "team-east",
    max_iterations: 1,
    source_ids: [LETTER.id, GONE], // the second was deleted since; it is dropped
  });

  function serveEarlier(
    answer: () => Response | Promise<Response> = () => HttpResponse.json(EARLIER),
  ) {
    serve();
    server.use(http.get(`*/api/runs/${RUN_ID}`, answer));
  }

  it("prefills the writer guidance from the earlier run as stored, reviewer notes included (CRL-132)", async () => {
    const stored = "Lead with capacity.\nReviewer note: Add the 2027 date";
    serveEarlier(() => HttpResponse.json({ ...EARLIER, extra_guidance: stored }));
    renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Guidance for the writer" })).toHaveValue(stored),
    );
  });

  it("a revision's guidance over the limit opens the fold, says to shorten it and holds Write (CRL-132)", async () => {
    // a revision's stored guidance carries the reviewer notes, so it can pass the 8,000 a new
    // run accepts; sending it would only earn a 422
    const long = "g".repeat(GUIDANCE_MAX_LENGTH - 10) + "\nReviewer note: add the 2027 date";
    serveEarlier(() => HttpResponse.json({ ...EARLIER, extra_guidance: long }));
    renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    const box = screen.getByRole("textbox", { name: "Guidance for the writer" });
    await waitFor(() => expect(box).toHaveValue(long));
    expect(screen.getByText("More options").closest("details")).toHaveAttribute("open");
    expect(box).toBeInvalid();
    expect(box).toHaveAccessibleDescription(
      `${long.length.toLocaleString()} of 8,000 characters Shorten the guidance to write the report.`,
    );
    const start = screen.getByRole("button", { name: "Write the report" });
    expect(start).toBeDisabled();
    fireEvent.change(box, { target: { value: long.slice(0, GUIDANCE_MAX_LENGTH) } });
    expect(screen.queryByText("Shorten the guidance to write the report.")).toBeNull();
    expect(box).toBeValid();
    expect(start).toBeEnabled();
  });

  it("prefills the statement, sources, profile and rounds, then drops `from` so a reload keeps the edits", async () => {
    serveEarlier();
    // the run wins over a draft left on the project
    sessionStorage.setItem(
      key,
      JSON.stringify({ statement: "old", profile: null, maxIterations: 2 }),
    );
    const { router, user } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    const box = screen.getByRole("textbox", { name: "Value statement" });
    await waitFor(() => expect(box).toHaveValue("Burgas matters to shippers"));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("team-east"),
    );
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(1);
    await waitFor(() => expect(router.state.location.search).not.toContain("from="));
    expect(chosenIn(router.state.location.search)).toBe(LETTER.id);
    expect(router.state.historyAction).toBe("REPLACE");
    expect(
      await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
    ).not.toBeChecked();

    await user.type(box, " in winter");
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toMatchObject({
        statement: "Burgas matters to shippers in winter",
      }),
    );
    const url = `/new${router.state.location.search}`;
    cleanup(); // the reload
    renderApp(url);
    expect(await screen.findByRole("textbox", { name: "Value statement" })).toHaveValue(
      "Burgas matters to shippers in winter",
    );
    expect(
      await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
    ).not.toBeChecked();
  });

  it("keeps what the analyst writes while the run loads, and still takes its sources", async () => {
    const held = deferred();
    serveEarlier(async () => {
      await held.promise;
      return HttpResponse.json(EARLIER);
    });
    const { router, user } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
    const box = screen.getByRole("textbox", { name: "Value statement" });
    await user.type(box, "My own");
    held.resolve();
    await waitFor(() => expect(router.state.location.search).not.toContain("from="));
    expect(chosenIn(router.state.location.search)).toBe(LETTER.id);
    expect(box).toHaveValue("My own");
    expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("");
  });

  it("shows a run that cannot be read by the statement, drops `from` and leaves the form as it was (CRL-108)", async () => {
    serveEarlier(() => HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 }));
    const { router } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    const statement = screen.getByRole("region", { name: "Value statement" });
    expect(await within(statement).findByRole("alert")).toHaveTextContent("not found");
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${project.id}`));
    expect(router.state.historyAction).toBe("REPLACE");
    // the error stays once `from` has left the URL
    expect(within(statement).getByRole("alert")).toHaveTextContent("not found");
    expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue("");
    expect(
      screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
    ).toBeChecked();

    // another link that can be read fills the form, with no error
    const next = "77777777-7777-7777-7777-777777777777";
    server.use(
      http.get(`*/api/runs/${next}`, () => HttpResponse.json({ ...EARLIER, run_id: next })),
    );
    await act(() => router.navigate(`/new?project=${project.id}&from=${next}`));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue(
        "Burgas matters to shippers",
      ),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a run that cannot be read: its error does not come back after another project (CRL-108)", async () => {
    serveEarlier(() => HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 }));
    server.use(
      http.get("*/api/projects", () => HttpResponse.json([project, OTHER])),
      http.get(`*/api/projects/${OTHER.id}/sources`, () => HttpResponse.json([])),
    );
    const { router } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("not found");
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${project.id}`));
    // another project drops it, and it does not come back with this project
    await act(() => router.navigate(`/new?project=${OTHER.id}`));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    await act(() => router.navigate(`/new?project=${project.id}`));
    await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
    expect(screen.queryByText(/not found/)).toBeNull();
  });

  it("ignores a run of another project (CRL-108)", async () => {
    serveEarlier(() =>
      HttpResponse.json({ ...EARLIER, project_id: "66666666-6666-6666-6666-666666666666" }),
    );
    const { router } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await waitFor(() => expect(router.state.location.search).toBe(`?project=${project.id}`));
    expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("");
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(2);
    expect(
      await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
    ).toBeChecked(); // every source, as without the link
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a run's statement over the limit shows the count, says to shorten it and holds Write (CRL-108)", async () => {
    const long = "x".repeat(VALUE_STATEMENT_MAX_LENGTH + 5);
    serveEarlier(() => HttpResponse.json({ ...EARLIER, value_statement: long }));
    const { user } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    const box = screen.getByRole("textbox", { name: "Value statement" });
    await waitFor(() => expect(box).toHaveValue(long));
    expect(screen.getByText("4,005 of 4,000 characters")).toBeInTheDocument();
    expect(screen.getByText("Shorten the statement to write the report.")).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Write the report" });
    expect(start).toBeDisabled();
    await user.type(box, "{Backspace>5/}");
    expect(box).toHaveValue("x".repeat(VALUE_STATEMENT_MAX_LENGTH));
    expect(screen.queryByText("Shorten the statement to write the report.")).toBeNull();
    expect(start).toBeEnabled();
  });

  it("a stale profile in the draft does not keep a run from filling the form (CRL-108)", async () => {
    serveEarlier(async () => {
      await delay(300); // the packs are read well before the run
      return HttpResponse.json(EARLIER);
    });
    sessionStorage.setItem(
      key,
      JSON.stringify({ statement: "old", profile: "retired", maxIterations: null }),
    );
    const { router } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await screen.findByRole("option", { name: "team-east" });
    await waitFor(() => expect(router.state.location.search).not.toContain("from="));
    const box = screen.getByRole("textbox", { name: "Value statement" });
    await waitFor(() => expect(box).toHaveValue("Burgas matters to shippers"));
    expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("team-east");
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(1);
    expect(screen.queryByText(/no longer available/)).toBeNull();
  });

  it("a run's profile that cannot be chosen now goes back to the default, with a note (CRL-108)", async () => {
    serveEarlier(() => HttpResponse.json({ ...EARLIER, profile: "draft-west" }));
    let body: { profile?: unknown } = {};
    server.use(
      http.post("*/api/runs", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ detail: "stop here" }, { status: 422 });
      }),
    );
    const { user } = renderApp(`/new?project=${project.id}&from=${RUN_ID}`);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue(
        "Burgas matters to shippers",
      ),
    );
    expect(
      await screen.findByText(
        "Team profile “draft-west” is no longer available, so no team profile is used.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue(""),
    );
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem(key) ?? "null")).toMatchObject({ profile: null }),
    );
    await user.click(screen.getByRole("button", { name: "Write the report" }));
    await screen.findByRole("alert");
    expect(body.profile).toBeNull();
  });

  it("takes up the gate's suggested scope from the run's outcome", async () => {
    serveEarlier(() => HttpResponse.json({ ...EARLIER, profile: null })); // the default profile
    server.use(
      http.get(`*/api/runs/${RUN_ID}/trace`, () =>
        HttpResponse.json({
          ...runTrace,
          summary: {
            ...runTrace.summary,
            state: "gate_rejected",
            status: null,
            gate: {
              supported: false,
              substance: "insufficient",
              reasons: ["The sources never mention Burgas."],
              evidence: [],
              suggested_scope: "Varna's grain terminal matters to shippers",
            },
          },
        }),
      ),
    );
    const { router, user } = renderApp(`/runs/${RUN_ID}`);
    await user.click(await screen.findByRole("link", { name: "Use the suggested scope" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/new"));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue(
        "Varna's grain terminal matters to shippers",
      ),
    );
    await waitFor(() => expect(router.state.location.search).not.toContain("from="));
    expect(chosenIn(router.state.location.search)).toBe(LETTER.id);
    expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("");
    expect(screen.getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(1);
  });
});
