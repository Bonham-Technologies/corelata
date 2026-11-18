import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setEventSourceFactory } from "../../api/events";
import { POLL_MS } from "../../api/runs";
import { FakeEventSource } from "../../test/fake-events";
import { expectNoEngineWords } from "../../test/engine-words";
import { reportJson, RUN_ID, runProgress, runTrace } from "../../test/fixtures";
import { runRefetchInterval } from "../../test/poll";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

beforeEach(() => {
  FakeEventSource.instances = [];
  setEventSourceFactory((url) => new FakeEventSource(url));
});
afterEach(() => setEventSourceFactory(undefined));

function renderTerminal(overrides: Parameters<typeof runProgress>[0]) {
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress(overrides))));
  return renderApp(`/runs/${RUN_ID}`);
}

function traceWithGate(gate: unknown) {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ ...runTrace, summary: { ...runTrace.summary, gate } }),
    ),
  );
}

it("says how many standards a delivered report did not meet and surfaces an export failure", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({
        ...reportJson,
        metadata: { ...reportJson.metadata, status: "findings_open", open_findings: ["a@1"] },
      }),
    ),
  );
  renderTerminal({
    state: "completed",
    status: "findings_open",
    export_error: "pdf export failed",
  });
  expect(
    await screen.findByText("1 standard not met; they're listed under Standards."),
  ).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("pdf export failed");
});

it("falls back to a generic message for a failed run without an error", async () => {
  renderTerminal({ state: "failed", error: null });
  expect(await screen.findByRole("alert")).toHaveTextContent("No reason was recorded.");
});

it("shows a rejection without a suggested scope", async () => {
  traceWithGate({
    supported: false,
    substance: "insufficient",
    reasons: ["No overlap."],
    evidence: [],
    suggested_scope: null,
  });
  renderTerminal({ state: "gate_rejected" });
  expect(await screen.findByText("No overlap.")).toBeInTheDocument();
  expect(screen.queryByText("Suggested scope:")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Use the suggested scope" })).not.toBeInTheDocument();
});

describe("starting again from the run (CRL-84)", () => {
  const again = `/new?project=${runProgress().project_id}&from=${RUN_ID}`;

  it("carries the run on Try another statement and Use the suggested scope", async () => {
    traceWithGate({
      supported: false,
      substance: "insufficient",
      reasons: ["No overlap."],
      evidence: [],
      suggested_scope: "Write about Burgas.",
    });
    renderTerminal({ state: "gate_rejected" });
    expect(await screen.findByRole("link", { name: "Use the suggested scope" })).toHaveAttribute(
      "href",
      again,
    );
    expect(screen.getByRole("link", { name: "Try another statement" })).toHaveAttribute(
      "href",
      again,
    );
  });

  it.each(["failed", "cancelled"] as const)(
    "carries the run on Start a new report after a %s run",
    async (state) => {
      renderTerminal({ state });
      expect(await screen.findByRole("link", { name: "Start a new report" })).toHaveAttribute(
        "href",
        again,
      );
    },
  );
});

it("shows a trace failure for a rejected run inline and still offers a new run", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "trace unavailable" }, { status: 500 }),
    ),
  );
  renderTerminal({ state: "gate_rejected" });
  expect(await screen.findByRole("alert")).toHaveTextContent("trace unavailable");
  expect(screen.getByRole("link", { name: "Try another statement" })).toBeInTheDocument();
});

it("shows only the headline for a rejected run whose trace has no gate", async () => {
  traceWithGate(null);
  renderTerminal({ state: "gate_rejected" });
  expect(
    await screen.findByText("The value check didn't find this in the sources."),
  ).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});

it("polls from the start without EventSource and shows the attempt number", async () => {
  setEventSourceFactory(null);
  const { queryClient } = renderTerminal({ state: "drafting", attempts: 2 });
  expect(
    await screen.findByText("Live updates are off; checking every few seconds."),
  ).toBeInTheDocument();
  expect(screen.getByText(/Started 2 times/)).toBeInTheDocument();
  expect(FakeEventSource.instances).toHaveLength(0);
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS);
});

it("shows a missing run inline", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 }),
    ),
  );
  renderApp(`/runs/${RUN_ID}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("not found");
});

it("shows a cancel failure inline and keeps the cancel button", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
    http.post(`*/api/runs/${RUN_ID}/cancel`, () =>
      HttpResponse.json({ detail: "run is already finishing" }, { status: 409 }),
    ),
  );
  const { user } = renderApp(`/runs/${RUN_ID}`);
  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("run is already finishing");
  expect(screen.getByRole("button", { name: "Stop writing…" })).toBeInTheDocument();
});

it("says when a cancel arrived too late to stop a delivered report", async () => {
  renderTerminal({ state: "completed", status: "clean", cancel_requested: true });
  expect(
    await screen.findByText(/A stop was asked for, but the report had already finished/),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review the report" })).toBeInTheDocument();
});

it("says a report was checked in part when findings_open has no open rule", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({
        ...reportJson,
        metadata: { ...reportJson.metadata, status: "findings_open", open_findings: [] },
      }),
    ),
  );
  renderTerminal({ state: "completed", status: "findings_open" });
  expect(
    await screen.findByText("Checked in part: it was delivered without a full check."),
  ).toBeInTheDocument();
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});

it("falls back to a general line when the report's own file does not load", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({ detail: "unavailable" }, { status: 500 }),
    ),
  );
  renderTerminal({ state: "completed", status: "findings_open" });
  expect(
    await screen.findByText("Some standards are not met; they're listed under Standards."),
  ).toBeInTheDocument();
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});

it("keeps engine words off a rejected report's page", async () => {
  traceWithGate({
    supported: false,
    substance: "insufficient",
    reasons: ["No overlap."],
    evidence: [],
    suggested_scope: "Write about Burgas.",
  });
  renderTerminal({ state: "gate_rejected" });
  await screen.findByText("No overlap.");
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});

it("says what the sources did not support: the statement, directly above the reasons (CRL-101)", async () => {
  traceWithGate({
    supported: false,
    substance: "insufficient",
    reasons: ["No overlap."],
    evidence: [],
    suggested_scope: null,
  });
  renderTerminal({ state: "gate_rejected" });
  const reasons = (await screen.findByText("No overlap.")).closest("ul")!;
  const outcome = screen.getByRole("region", { name: "Outcome" });
  const shown = within(outcome).getByRole("region", { name: "Value statement" });
  expect(shown).toHaveTextContent(runProgress().value_statement);
  // directly above the reasons: the reasons' block is the statement's next sibling
  expect(shown.nextElementSibling?.contains(reasons)).toBe(true);
  expectNoEngineWords(screen.getByRole("main"), { exceptRawErrors: true });
});
