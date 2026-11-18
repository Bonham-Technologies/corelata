import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RUN_ID, runTrace } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { expectNoEngineWords } from "../../test/engine-words";
import { SourcesTab } from "./SourcesTab";

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
