import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setEventSourceFactory } from "../../api/events";
import { POLL_MS, runKeys } from "../../api/runs";
import { deferred } from "../../test/deferred";
import { FakeEventSource } from "../../test/fake-events";
import { fakeOverflow, LONG_STATEMENT } from "../../test/layout";
import { expectNoEngineWords } from "../../test/engine-words";
import {
  PARENT_RUN_ID,
  parentReportJson,
  project,
  reportJson,
  RETURN_NOTE,
  returnedParent,
  RUN_ID,
  runProgress,
  runTrace,
} from "../../test/fixtures";
import { runRefetchInterval } from "../../test/poll";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

beforeEach(() => {
  FakeEventSource.instances = [];
  setEventSourceFactory((url) => new FakeEventSource(url));
});
afterEach(() => setEventSourceFactory(undefined));

const usage = { calls: 3, tokens_in: 4200, tokens_out: 900, by_role: {} };

/** The step the page marks as in progress (aria-current="step"), checked by its name. */
function currentStep(name: string): HTMLElement {
  const step = screen
    .getByRole("list", { name: "Steps" })
    .querySelector<HTMLElement>('[aria-current="step"]');
  expect(step?.querySelector(".step-name")).toHaveTextContent(name);
  return step!;
}
const findCurrentStep = (name: string) => waitFor(() => currentStep(name));

it("shows the live run, applies stream events and links to the review when done (test_terminal_event_closes_the_stream_and_links_to_review)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "gating", usage })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("heading", { name: "Writing the report" })).toBeInTheDocument();
  expect(currentStep("Checking the value statement")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Token usage" })).toHaveTextContent("3 model calls");
  expect(screen.getByRole("status", { name: "Token usage" })).toHaveTextContent("4,200 in");
  const source = FakeEventSource.last();
  source.emit("progress", runProgress({ state: "drafting", iteration: 0, usage }));
  expect(await findCurrentStep("Drafting")).toBeInTheDocument();
  source.emit(
    "progress",
    runProgress({
      state: "completed",
      status: "clean",
      iteration: 1,
      usage,
      finished_at: "2026-10-13T10:05:00Z",
    }),
  );
  expect(await screen.findByRole("link", { name: "Review the report" })).toHaveAttribute(
    "href",
    `/runs/${RUN_ID}/review`,
  );
  expect(screen.getByText("Meets the standards.")).toBeInTheDocument();
  expect(source.closed).toBe(true);
  expect(screen.queryByRole("button", { name: "Stop writing…" })).not.toBeInTheDocument();
});

it("shows the gate's reasons for a rejected run with a way to start again", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "gate_rejected" })),
    ),
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
            reasons: ["The sources never mention Varna."],
            evidence: [],
            suggested_scope: "Write about Burgas instead.",
          },
        },
      }),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByText("The sources never mention Varna.")).toBeInTheDocument();
  expect(screen.getByText("Write about Burgas instead.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Try another statement" })).toHaveAttribute(
    "href",
    `/new?project=${runProgress().project_id}&from=${RUN_ID}`,
  );
  expect(FakeEventSource.instances).toHaveLength(0); // terminal from the start: no stream
});

it("shows a failure and a cancelled run", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "failed", error: "writer: context window exceeded" })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("writer: context window exceeded");
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "cancelled", cancel_requested: true })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(
    await screen.findByRole("heading", { name: "Stopped before the report was written." }),
  ).toBeInTheDocument();
  // the failed run's page above and the cancelled run's both offer a new report
  expect(screen.getAllByRole("link", { name: "Start a new report" })).toHaveLength(2);
});

it("cancels after a confirmation (test for the cancel path)", async () => {
  let cancelled = false;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
    http.post(`*/api/runs/${RUN_ID}/cancel`, () => {
      cancelled = true;
      return HttpResponse.json(runProgress({ state: "drafting", cancel_requested: true }));
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}`);
  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
  await user.click(screen.getByRole("button", { name: "Keep going" }));
  expect(cancelled).toBe(false);
  await user.click(screen.getByRole("button", { name: "Stop writing…" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
  await waitFor(() => expect(cancelled).toBe(true));
  expect(await screen.findByText("Stopping after the current step…")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Stop writing…" })).not.toBeInTheDocument();
});

it("offers the cancel again once a stopping run's worker is gone (CRL-49)", async () => {
  let gone = false;
  let cancels = 0;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({ state: "drafting", cancel_requested: true, worker_gone: gone }),
      ),
    ),
    http.post(`*/api/runs/${RUN_ID}/cancel`, () => {
      cancels += 1;
      return HttpResponse.json(runProgress({ state: "cancelled", cancel_requested: true }));
    }),
  );
  const { user, queryClient } = renderApp(`/runs/${RUN_ID}`);
  // still moving: the wait, and nothing to press
  expect(await screen.findByText("Stopping after the current step…")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Stop/ })).not.toBeInTheDocument();
  gone = true;
  await queryClient.invalidateQueries({ queryKey: ["runs", RUN_ID], exact: true });
  expect(await screen.findByText(/stopped responding/)).toBeInTheDocument();
  expect(screen.queryByText(/it keeps going|starts over/)).not.toBeInTheDocument();
  expect(screen.queryByText("Stopping after the current step…")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Stop now…" }));
  expect(within(screen.getByRole("dialog")).getByText(/It stops now/)).toBeInTheDocument();
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
  await waitFor(() => expect(cancels).toBe(1));
  expect(
    await screen.findByRole("heading", { name: "Stopped before the report was written." }),
  ).toBeInTheDocument();
});

it("says a run whose worker is gone stopped responding, without a cancel, and offers Stop now (CRL-69)", async () => {
  let gone = false;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "drafting", worker_gone: gone })),
    ),
  );
  const { queryClient } = renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByText(/You can leave this page; it keeps going/)).toBeInTheDocument();
  gone = true;
  await queryClient.invalidateQueries({ queryKey: ["runs", RUN_ID], exact: true });
  expect(
    await screen.findByText(/The process writing this report stopped responding/),
  ).toHaveTextContent("starts over when it is running again, or you can end it with Stop now….");
  expect(screen.queryByText(/it keeps going/)).not.toBeInTheDocument();
  expect(screen.queryByText(/can't stop on its own/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stop now…" })).toBeInTheDocument();
  gone = false; // a worker re-queued it: it is moving again
  await queryClient.invalidateQueries({ queryKey: ["runs", RUN_ID], exact: true });
  expect(await screen.findByText(/it keeps going/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stop writing…" })).toBeInTheDocument();
});

it("ends on a deleted event with the not-found message (test_deleted_event_shows_not_found)", async () => {
  let deleted = false;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      deleted
        ? HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 })
        : HttpResponse.json(runProgress({ state: "gating" })),
    ),
  );
  const { queryClient } = renderApp(`/runs/${RUN_ID}`);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  await findCurrentStep("Checking the value statement");
  deleted = true;
  FakeEventSource.last().emit("deleted", {});
  expect(await screen.findByRole("heading", { name: "Report not found" })).toBeInTheDocument();
  await waitFor(() => expect(document.title).toBe("Report not found – Corelata"));
  expect(FakeEventSource.last().closed).toBe(true);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs", RUN_ID], exact: true });
});

it("a run that does not exist says so, names the tab and offers a new report (CRL-130)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 }),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("heading", { name: "Report not found" })).toBeInTheDocument();
  expect(screen.getByText(/does not exist, or it was deleted/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Start a new report" })).toHaveAttribute("href", "/new");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText(new RegExp(RUN_ID))).toBeNull();
  await waitFor(() => expect(document.title).toBe("Report not found – Corelata"));
});

it("a truncated run link says the report was not found, not the validation error (CRL-130)", async () => {
  const truncated = RUN_ID.slice(0, 20);
  server.use(
    http.get(`*/api/runs/${truncated}`, () =>
      HttpResponse.json(
        { detail: [{ loc: ["path", "run_id"], msg: "Input should be a valid UUID" }] },
        { status: 422 },
      ),
    ),
  );
  renderApp(`/runs/${truncated}`);
  expect(await screen.findByRole("heading", { name: "Report not found" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps the error line when the run cannot be read for another reason (CRL-130)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 }),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("the database is unavailable");
  expect(screen.queryByRole("heading", { name: "Report not found" })).toBeNull();
});

it("polls when the stream gave up, and stops once the run is terminal", async () => {
  let state: "gating" | "completed" = "gating";
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state }))));
  const { queryClient } = renderApp(`/runs/${RUN_ID}`);
  await findCurrentStep("Checking the value statement");
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false); // the stream delivers updates
  act(() => FakeEventSource.last().fail());
  expect(
    await screen.findByText("Live updates are off; checking every few seconds."),
  ).toBeInTheDocument();
  await waitFor(() => expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS));
  state = "completed";
  await act(() => queryClient.refetchQueries({ queryKey: ["runs", RUN_ID] }));
  expect(await screen.findByRole("link", { name: "Review the report" })).toBeInTheDocument();
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false);
});

it("does not carry a stream failure over to another run", async () => {
  const other = "22222222-2222-4222-8222-222222222222";
  server.use(
    http.get(`*/api/runs/:id`, ({ params }) =>
      HttpResponse.json(runProgress({ run_id: String(params.id), state: "gating" })),
    ),
  );
  const { router } = renderApp(`/runs/${RUN_ID}`);
  await findCurrentStep("Checking the value statement");
  act(() => FakeEventSource.last().fail());
  await screen.findByText("Live updates are off; checking every few seconds.");
  await act(() => router.navigate(`/runs/${other}`));
  await waitFor(() =>
    expect(screen.queryByText("Live updates are off; checking every few seconds.")).toBeNull(),
  );
  await waitFor(() => expect(FakeEventSource.last().url).toContain(other));
});

it("leads back to the project, says it can be left, keeps the detail folded, and names the tab", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({
          state: "conveying",
          iteration: 1,
          usage,
          stages: [
            {
              stage: "ingesting",
              iteration: 0,
              ok: true,
              error: null,
              output: null,
              started_at: "2026-10-13T10:02:00Z",
              finished_at: "2026-10-13T10:02:01Z",
            },
          ],
        }),
      ),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  const main = screen.getByRole("main");
  const crumb = await within(main).findByRole("navigation", { name: "Breadcrumb" });
  expect(await within(crumb).findByRole("link", { name: project.name })).toHaveAttribute(
    "href",
    `/new?project=${project.id}`,
  );
  expect(currentStep("Editing for the reader")).toHaveTextContent("now · revision 1 of 2");
  expect(
    within(main).getByText(
      "This usually takes a few minutes. You can leave this page; it keeps going.",
    ),
  ).toBeInTheDocument();
  const details = within(main).getByText("Details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByText("Reading the sources: 1.0 s")).toBeInTheDocument();
  expect(within(details).getByRole("status", { name: "Token usage" })).toHaveTextContent(
    "3 model calls",
  );
  await waitFor(() => expect(document.title).toBe(`Writing… – ${project.name}`));
  expectNoEngineWords(main);
});

it("asks before it stops a report, in the reader's words", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
  );
  const { user } = renderApp(`/runs/${RUN_ID}`);
  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
  const dialog = screen.getByRole("dialog", { name: "Stop this report?" });
  expect(dialog).toHaveTextContent(
    "It stops after the step in progress; no report will be produced.",
  );
  expect(within(dialog).getByRole("button", { name: "Keep going" })).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Stop" })).toHaveClass("danger");
});

it("ends with the outcome's heading, one way on, and the report's title on the tab", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean" })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("heading", { name: "Ready to review." })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review the report" })).toHaveClass("primary");
  expect(screen.queryByRole("button", { name: "Stop writing…" })).toBeNull();
  await waitFor(() => expect(document.title).toBe(`✓ Ready to review – ${reportJson.title}`));
  expect(screen.getAllByRole("listitem").at(-1)).toHaveAttribute("data-status", "done");
});

it("names a report that did not get written on the tab by its status", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "gate_rejected" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(
    await screen.findByRole("heading", { name: "Not supported by the sources." }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(document.title).toBe(`Not supported by the sources – ${project.name}`),
  );
  expectNoEngineWords(screen.getByRole("main"));
});

it("shows the failed step's error under the step as well as in the outcome", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({
          state: "failed",
          error: "model unreachable",
          stages: [
            {
              stage: "gating",
              iteration: 0,
              ok: false,
              error: "gate model unreachable",
              output: null,
              started_at: "2026-10-13T10:02:00Z",
              finished_at: "2026-10-13T10:02:03Z",
            },
          ],
        }),
      ),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  const steps = await screen.findByRole("list", { name: "Steps" });
  expect(within(steps).getByText("gate model unreachable")).toHaveClass("step-error");
  expect(screen.getByRole("alert")).toHaveTextContent("model unreachable");
  // The engine's raw error text is shown on purpose, so only elements marked data-raw-error
  // are left out of the check.
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});

it.each([
  ["clean", { state: "completed", status: "clean" }],
  ["with findings open", { state: "completed", status: "findings_open" }],
  ["cancelled", { state: "cancelled" }],
] as const)("keeps engine words off a %s report's page", async (_name, overrides) => {
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress(overrides))));
  renderApp(`/runs/${RUN_ID}`);
  await screen.findByRole("region", { name: "Outcome" });
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});

it("says Stopping… on the dialog's button while the cancel is out (CRL-43)", async () => {
  const held = deferred();
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
    http.post(`*/api/runs/${RUN_ID}/cancel`, async () => {
      await held.promise;
      return HttpResponse.json(runProgress({ state: "drafting", cancel_requested: true }));
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}`);
  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
  expect(
    await within(screen.getByRole("dialog")).findByRole("button", { name: "Stopping…" }),
  ).toBeDisabled();
  held.resolve();
  expect(await screen.findByText("Stopping after the current step…")).toBeInTheDocument();
});

describe("the value statement (CRL-101)", () => {
  const statement = runProgress().value_statement;

  it.each([
    ["while it is written", { state: "drafting" }],
    ["once it is ready", { state: "completed", status: "clean" }],
    ["when it is not supported", { state: "gate_rejected" }],
    ["when it failed", { state: "failed", error: "model unreachable" }],
    ["once stopped", { state: "cancelled" }],
  ] as const)("shows it, labelled, under the heading %s", async (_name, overrides) => {
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress(overrides))),
      http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    );
    renderApp(`/runs/${RUN_ID}`);
    const shown = await screen.findByRole("region", { name: "Value statement" });
    expect(within(shown).getByText(statement)).toHaveAttribute("dir", "auto");
    expect(screen.getAllByRole("region", { name: "Value statement" })).toHaveLength(1);
    // under the heading: nothing but the heading comes before it on the page
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.nextElementSibling?.contains(shown)).toBe(true);
    expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
  });

  it("folds a statement longer than three lines", async () => {
    fakeOverflow();
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(runProgress({ state: "drafting", value_statement: LONG_STATEMENT })),
      ),
    );
    const { user } = renderApp(`/runs/${RUN_ID}`);
    const shown = await screen.findByRole("region", { name: "Value statement" });
    const text = within(shown).getByText(LONG_STATEMENT);
    expect(text).toHaveAttribute("data-folded");
    await user.click(within(shown).getByRole("button", { name: "Show the whole statement" }));
    expect(text).not.toHaveAttribute("data-folded");
    expect(within(shown).getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });
});

describe("a revised report (CRL-102)", () => {
  function serveRevision(parent: Response | ReturnType<typeof returnedParent>) {
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(runProgress({ state: "drafting", parent_run_id: PARENT_RUN_ID })),
      ),
      http.get(`*/api/runs/${PARENT_RUN_ID}`, () =>
        parent instanceof Response ? parent : HttpResponse.json(parent),
      ),
      http.get(`*/api/runs/${PARENT_RUN_ID}/exports/report.json`, () =>
        HttpResponse.json(parentReportJson),
      ),
    );
  }

  it("says it is a revision of the original, linked to its review, with the note", async () => {
    serveRevision(returnedParent());
    renderApp(`/runs/${RUN_ID}`);
    const original = await screen.findByRole("region", { name: "Original report" });
    const link = await within(original).findByRole("link", { name: parentReportJson.title });
    expect(link).toHaveAttribute("href", `/runs/${PARENT_RUN_ID}/review`);
    expect(link.closest("p")).toHaveTextContent(`Revision of ${parentReportJson.title}`);
    expect(await within(original).findByText(RETURN_NOTE)).toBeInTheDocument();
    expectNoEngineWords(screen.getByRole("main"));
  });

  it("names the original only once its title is read, and holds the note until then", async () => {
    const held = deferred();
    serveRevision(returnedParent());
    let asked = false;
    server.use(
      http.get(`*/api/runs/${PARENT_RUN_ID}/exports/report.json`, async () => {
        asked = true;
        await held.promise;
        return HttpResponse.json(parentReportJson);
      }),
    );
    renderApp(`/runs/${RUN_ID}`);
    const original = await screen.findByRole("region", { name: "Original report" });
    await waitFor(() => expect(asked).toBe(true)); // the original is read; its title is not yet
    expect(within(original).queryByRole("link")).toBeNull();
    expect(original).not.toHaveTextContent("Revision of");
    expect(original).not.toHaveTextContent(RETURN_NOTE);
    held.resolve();
    expect(
      await within(original).findByRole("link", { name: parentReportJson.title }),
    ).toBeInTheDocument();
    expect(original).toHaveTextContent(RETURN_NOTE);
  });

  it("links an original without a report to its outcome, by a plain name", async () => {
    serveRevision(returnedParent({ state: "gate_rejected", status: null, review: null }));
    renderApp(`/runs/${RUN_ID}`);
    const original = await screen.findByRole("region", { name: "Original report" });
    await waitFor(() =>
      expect(within(original).getByRole("link", { name: "the original report" })).toHaveAttribute(
        "href",
        `/runs/${PARENT_RUN_ID}`,
      ),
    );
    expect(original).toHaveTextContent("Revision of the original report");
  });

  it("keeps the link to the original's review when the original can't be read just now", async () => {
    serveRevision(HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 }));
    const { queryClient } = renderApp(`/runs/${RUN_ID}`);
    const original = await screen.findByRole("region", { name: "Original report" });
    await waitFor(() =>
      expect(queryClient.getQueryState(runKeys.one(PARENT_RUN_ID))?.status).toBe("error"),
    );
    expect(within(original).getByRole("link", { name: "the original report" })).toHaveAttribute(
      "href",
      `/runs/${PARENT_RUN_ID}/review`,
    );
    expect(original).toHaveTextContent("Revision of the original report");
    expect(original).not.toHaveTextContent(RETURN_NOTE);
  });
});

it("calls a check of a finished report Checking the report (CRL-94)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "structuring", kind: "check", usage })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("heading", { name: "Checking the report" })).toBeInTheDocument();
  expect(currentStep("Reading the report")).toBeInTheDocument();
});

it("shows the guidance the writer was given, only when there is some (CRL-132)", async () => {
  const guidance = "Lead with capacity.\nReviewer note: Add the 2027 date";
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "gating", extra_guidance: guidance })),
    ),
  );
  const first = renderApp(`/runs/${RUN_ID}`);
  const block = await screen.findByRole("region", { name: "Guidance for the writer" });
  expect(block).toHaveTextContent("Lead with capacity.");
  expect(block).toHaveTextContent("Reviewer note: Add the 2027 date");
  first.queryClient.clear();
  cleanup();
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "gating", extra_guidance: "" })),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  await screen.findByRole("heading", { name: "Writing the report" });
  expect(screen.queryByRole("region", { name: "Guidance for the writer" })).toBeNull();
});
