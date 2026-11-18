import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { reportKeys } from "../../api/reports";
import { deferred } from "../../test/deferred";
import { claimProvenance, reportJson, RUN_ID } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { ProvenanceTab } from "./ProvenanceTab";

function Host({ initial = null }: { initial?: string | null }) {
  const [claim, setClaim] = useState<string | null>(initial);
  return <ProvenanceTab runId={RUN_ID} selectedClaim={claim} onSelectClaim={setClaim} />;
}

beforeEach(() => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/claims/c3`, () => HttpResponse.json(claimProvenance)),
    http.get(`*/api/runs/${RUN_ID}/claims/c1`, () =>
      HttpResponse.json({
        ...claimProvenance,
        claim: reportJson.claims[0],
        evidence: [claimProvenance.evidence[1]],
        cited_by: ["analysis[0].paragraphs[0]"],
      }),
    ),
  );
});

it("lists the claims, selects one and shows its evidence with locators and source names", async () => {
  const { user } = renderWithClient(<Host />);
  const list = await screen.findByRole("list", { name: "Claims" });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[1]).toHaveTextContent("Judgment · likely · 2 passages");
  await user.click(within(items[1]!).getByRole("button"));
  const evidence = await screen.findByRole("list", { name: "Evidence for claim c3" });
  const units = within(evidence).getAllByRole("listitem");
  expect(units).toHaveLength(2);
  expect(units[0]).toHaveTextContent("port.txt");
  expect(units[0]).toHaveTextContent("para:2");
  expect(units[0]).toHaveTextContent("Shippers expect waiting times");
  expect(
    screen.getByText("Cited in: Key judgments, item 1; Analysis, section 1, paragraph 2"),
  ).toBeInTheDocument();
  expect(within(items[1]!).getByRole("button")).toHaveAttribute("aria-pressed", "true");
});

it("marks the quoted words in each unit, and shows the whole unit for a quote it cannot find (CRL-93)", async () => {
  const { user } = renderWithClient(<Host />);
  const list = await screen.findByRole("list", { name: "Claims" });
  await user.click(within(within(list).getAllByRole("listitem")[1]!).getByRole("button"));
  const evidence = await screen.findByRole("list", { name: "Evidence for claim c3" });
  const [found, missing] = within(evidence).getAllByRole("blockquote");
  expect(found!.querySelector("mark")).toHaveTextContent(/^waiting times at Varna to fall$/);
  expect(found).toHaveTextContent("Shippers expect waiting times at Varna to fall by a third.");
  expect(missing!.querySelector("mark")).toBeNull();
  expect(missing).toHaveTextContent(
    /^The port of Varna will add a second grain terminal in 2027\.$/,
  );
  // a claim without quotes (a run with evidence_quotes off) shows its units unmarked
  await user.click(within(within(list).getAllByRole("listitem")[0]!).getByRole("button"));
  const plain = await screen.findByRole("list", { name: "Evidence for claim c1" });
  expect(plain.querySelector("mark")).toBeNull();
});

it("shows the evidence for a claim selected from the report (URL) and a claim lookup error", async () => {
  renderWithClient(<Host initial="c1" />);
  expect(await screen.findByRole("list", { name: "Evidence for claim c1" })).toBeInTheDocument();
  server.use(
    http.get(`*/api/runs/${RUN_ID}/claims/c9`, () =>
      HttpResponse.json({ detail: "claim c9 is not in the report" }, { status: 404 }),
    ),
  );
  renderWithClient(<Host initial="c9" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("claim c9 is not in the report");
});

it("says the evidence is loading while a selected claim's evidence loads (CRL-40)", async () => {
  const held = deferred();
  server.use(
    http.get(`*/api/runs/${RUN_ID}/claims/c3`, async () => {
      await held.promise;
      return HttpResponse.json(claimProvenance);
    }),
  );
  const { user } = renderWithClient(<Host />);
  const list = await screen.findByRole("list", { name: "Claims" });
  expect(screen.queryByText("Loading evidence…")).not.toBeInTheDocument(); // nothing selected
  await user.click(within(within(list).getAllByRole("listitem")[1]!).getByRole("button"));
  expect(await screen.findByText("Loading evidence…")).toHaveAttribute("role", "status");
  held.resolve();
  expect(await screen.findByRole("list", { name: "Evidence for claim c3" })).toBeInTheDocument();
  expect(screen.queryByText("Loading evidence…")).not.toBeInTheDocument();
});

it("leaving the page while evidence loads cancels it, and that is not an error (CRL-40)", async () => {
  const held = deferred();
  let request: Request | undefined;
  server.use(
    http.get(`*/api/runs/${RUN_ID}/claims/c1`, async ({ request: seen }) => {
      request = seen;
      await held.promise;
      return HttpResponse.json(claimProvenance);
    }),
  );
  const { queryClient, unmount } = renderWithClient(<Host initial="c1" />);
  expect(await screen.findByText("Loading evidence…")).toBeInTheDocument();
  await waitFor(() => expect(request).toBeDefined());
  unmount(); // the reviewer goes to another page
  await waitFor(() => expect(request!.signal.aborted).toBe(true));
  const state = queryClient.getQueryState(reportKeys.claim(RUN_ID, "c1"))!;
  expect(state.error).toBeNull(); // cancelled, not the network error
  expect(state.status).toBe("pending");
  expect(state.fetchStatus).toBe("idle");
  held.resolve();
});

it("asks for a selection when none is made", async () => {
  renderWithClient(<Host />);
  expect(
    await screen.findByText("Select a claim, here or in the report, to see its evidence."),
  ).toBeInTheDocument();
});

it("shows a claims list error", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({ detail: "run not found" }, { status: 404 }),
    ),
  );
  renderWithClient(<Host />);
  expect(await screen.findByRole("alert")).toHaveTextContent("run not found");
});
