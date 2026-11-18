import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RUN_ID, runTrace } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { describePriorReport, ProcessTab, stageName } from "./ProcessTab";

it("names a stage in the reader's words, and leaves one the app does not know as it is", () => {
  expect(stageName("auditing")).toBe("Checking against the standards (auditing)");
  expect(stageName("planning")).toBe("planning");
});

it("shows the stage timeline, what each draft changed and the usage by role", async () => {
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)));
  renderWithClient(<ProcessTab runId={RUN_ID} />);
  const stages = await screen.findByRole("table", { name: "Stage timeline" });
  expect(within(stages).getAllByRole("row")).toHaveLength(10);
  // the reader's word, then the engine's (M18 spec §4.4)
  expect(within(stages).getAllByRole("row")[2]).toHaveTextContent(
    "Checking the value statement (gating)",
  );
  expect(within(stages).getAllByRole("row")[2]).toHaveTextContent("2.3 s");
  const drafts = screen.getByRole("list", { name: "Drafts" });
  const items = within(drafts).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("writer, iteration 0: first draft");
  expect(items[1]).toHaveTextContent("title changed");
  expect(items[2]).toHaveTextContent("removed c2");
  expect(items[2]).toHaveTextContent("reworded c1");
  expect(items[2]).toHaveTextContent("key judgments changed");
  expect(items[2]).toHaveTextContent("sections changed: Analysis");
  expect(items[3]).toHaveTextContent("no changes");
  const usage = screen.getByRole("table", { name: "Token usage by role" });
  expect(within(usage).getAllByRole("row")[1]).toHaveTextContent("gate");
  expect(within(usage).getAllByRole("row")[1]).toHaveTextContent("1,200");
  expect(screen.getByText("8 model calls · 12,400 tokens in · 3,900 out")).toBeInTheDocument();
});

it("shows a trace error", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "run not found" }, { status: 404 }),
    ),
  );
  renderWithClient(<ProcessTab runId={RUN_ID} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("run not found");
});

it("shows failed stages, unknown stage names and every kind of draft change", async () => {
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      stages: [
        { stage: "mystery", iteration: 0, ok: false, duration_ms: 10, error: "boom" },
        { stage: "drafting", iteration: 0, ok: false, duration_ms: 10, error: null },
      ],
    },
    drafts: [
      {
        role: "writer",
        iteration: 1,
        changes: {
          title_changed: false,
          claims_added: ["c4"],
          claims_removed: [],
          claims_reworded: [],
          key_judgments_changed: false,
          sections_changed: [],
        },
      },
    ],
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<ProcessTab runId={RUN_ID} />);
  const stages = await screen.findByRole("table", { name: "Stage timeline" });
  const rows = within(stages).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("mystery");
  expect(rows[1]).toHaveTextContent("boom");
  expect(rows[2]).toHaveTextContent("failed");
  expect(screen.getByRole("list", { name: "Drafts" })).toHaveTextContent("added c4");
});

it("lists the earlier accepted reports the run read, and those the budget left out (CRL-97)", async () => {
  const report = {
    run_id: "r-earlier",
    title: "Varna capacity",
    accepted_at: "2026-11-12T09:00:00Z",
    key_judgments: [{ text: "Capacity grows.", confidence: "moderate" as const }],
    cut: false,
  };
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      prior_reports: [report, { ...report, run_id: "r-oldest", title: "Old", cut: true }],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<ProcessTab runId={RUN_ID} />);
  const list = await screen.findByRole("list", { name: "Earlier accepted reports" });
  const items = within(list).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("r-earlier Varna capacity");
  expect(items[0]).toHaveTextContent("1 key judgment read");
  expect(items[1]).toHaveTextContent("r-oldest Old");
  expect(items[1]).toHaveTextContent("left out: over the token budget");
  expect(describePriorReport({ ...report, key_judgments: [] })).toBe("0 key judgments read");
});

it("shows no earlier reports when the run read none", async () => {
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)));
  renderWithClient(<ProcessTab runId={RUN_ID} />);
  await screen.findByRole("table", { name: "Stage timeline" });
  expect(screen.queryByRole("list", { name: "Earlier accepted reports" })).toBeNull();
});
