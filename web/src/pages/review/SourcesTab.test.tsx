import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RUN_ID, runTrace } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { expectNoEngineWords } from "../../test/engine-words";
import { referenceLines, SourcesTab } from "./SourcesTab";

it("lists the run's sources with kind, units, digest flag and Coglossa run id", async () => {
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("port.txt");
  expect(rows[0]).toHaveTextContent("3 units");
  expect(rows[0]).toHaveTextContent("aaaaaaaaaaaa");
  expect(within(rows[0]!).getByTitle("a".repeat(64))).toHaveTextContent("aaaaaaaaaaaa");
  expect(rows[1]).toHaveTextContent("cccccccccccc");
  expect(within(table).getByRole("columnheader", { name: "SHA-256" })).toBeInTheDocument();
  expect(rows[1]).toHaveTextContent("Coglossa run run-42");
  expect(rows[1]).toHaveTextContent("Coglossa reliability tier B; summarised before drafting");
  expect(screen.getByText(/Standards pack icd203-base \(bbbbbbbbbbbb\)/)).toBeInTheDocument();
});

it("shows a trace error", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "run not found" }, { status: 404 }),
    ),
  );
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("run not found");
});

it("shows the profile, a missing Coglossa run id and singular units", async () => {
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      profile: "brief",
      sources: [
        { ...runTrace.summary.sources[1]!, coglossa_run_id: null, units: 1, digested: false },
      ],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  const row = within(table).getAllByRole("row")[1]!;
  expect(row).toHaveTextContent("Coglossa run ?");
  expect(row).toHaveTextContent("Coglossa reliability tier B");
  expect(row).not.toHaveTextContent(";");
  expect(row).toHaveTextContent("1 unit");
  expect(row).not.toHaveTextContent("1 units");
  expect(screen.getByText(/team profile brief/)).toBeInTheDocument();
});

it("says when a source's text was recovered by OCR, alongside the summary note", async () => {
  const [plain, coglossa] = runTrace.summary.sources;
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      sources: [
        { ...plain!, name: "scan.pdf", format: "pdf", ocr_pages: 1 },
        { ...coglossa!, ocr_pages: 3 },
      ],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows[0]).toHaveTextContent("text recovered by OCR (1 page)");
  expect(rows[0]).not.toHaveTextContent("summarised");
  expect(rows[1]).toHaveTextContent("summarised before drafting; text recovered by OCR (3 pages)");
  expectNoEngineWords(table);
});

it("flags passages that read as instructions to an AI and hidden passages (CRL-137)", async () => {
  const [plain, coglossa] = runTrace.summary.sources;
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      sources: [
        { ...plain!, name: "page.html", format: "html", suspect_units: 1, hidden_units: 2 },
        { ...coglossa!, suspect_units: 3, hidden_units: 1 },
      ],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(within(rows[0]!).getByText("1 passage read as instructions to an AI")).toHaveClass(
    "badge",
  );
  expect(within(rows[0]!).getByText("2 hidden passages withheld from the models")).toHaveClass(
    "badge",
  );
  expect(rows[1]).toHaveTextContent(
    "Coglossa reliability tier B; summarised before drafting" +
      "3 passages read as instructions to an AI" +
      "1 hidden passage withheld from the models",
  );
});

it("shows no flag for a source with nothing hidden or suspect", async () => {
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  expect(table.querySelector(".source-flag")).toBeNull();
});

it("labels each value of a source's reference as stated by the analyst or inferred (CRL-138)", async () => {
  const [plain, coglossa] = runTrace.summary.sources;
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      sources: [{ ...plain!, stated: { origin: "Varna Port Authority" } }, coglossa!],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  expect(within(table).getByRole("columnheader", { name: "Source reference" })).toBeVisible();
  const rows = within(table).getAllByRole("row").slice(1);
  await within(rows[0]!).findByText("Varna Port Authority");
  const lines = [...rows[0]!.querySelectorAll(".reference-line")].map((l) => l.textContent);
  expect(lines).toEqual([
    "Descriptor: official government publication inferred by model",
    "Reliability: The authority's own figures. inferred by model",
    "Origin: Varna Port Authority stated by analyst",
    "Access: direct inferred by model",
  ]);
  expect(within(rows[0]!).getByText("stated by analyst")).toHaveClass("badge");
  expect(rows[1]).toHaveTextContent("Descriptor: translated document inferred by model");
  expect(rows[1]).not.toHaveTextContent("Reliability");
  expectNoEngineWords(table);
});

it("shows only the analyst's values for a run without a report", async () => {
  const [plain, coglossa] = runTrace.summary.sources;
  const trace = {
    ...runTrace,
    summary: {
      ...runTrace.summary,
      state: "failed" as const,
      status: null,
      sources: [{ ...plain!, stated: { access: "indirect" } }, coglossa!],
    },
  };
  server.use(http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(trace)));
  renderWithClient(<SourcesTab runId={RUN_ID} />);
  const table = await screen.findByRole("table", { name: "Sources" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows[0]).toHaveTextContent("Access: indirect stated by analyst");
  expect(rows[1]!.querySelector(".reference-line")).toBeNull();
});

it("labels a stated value the report does not carry as the model's", () => {
  expect(
    referenceLines(
      { source_id: "src1", descriptor: "x", reliability_note: "" },
      { descriptor: "y" },
    ),
  ).toEqual([{ label: "Descriptor", value: "x", byAnalyst: false }]);
  expect(referenceLines(undefined, undefined)).toEqual([]);
});
