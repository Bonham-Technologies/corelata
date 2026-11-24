import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setEventSourceFactory } from "../../api/events";
import { POLL_MS } from "../../api/runs";
import type { ReviewState, RunState } from "../../api/types";
import {
  AUDIT_INCOMPLETE,
  claimProvenance,
  degradedReportJson,
  findings,
  PARENT_RUN_ID,
  parentReportJson,
  project,
  reportHtml,
  reportJson,
  resolvedPack,
  RETURN_NOTE,
  returnedParent,
  RUN_ID,
  runProgress,
  runTrace,
} from "../../test/fixtures";
import { deferred } from "../../test/deferred";
import { expectNoEngineWords, visiblePrimaryButtons } from "../../test/engine-words";
import { FakeEventSource } from "../../test/fake-events";
import { fakeOverflow, LONG_STATEMENT } from "../../test/layout";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

const banner = () => screen.getByRole("status", { name: "Where the review stands" });

const tabHandlers = [
  http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
  http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
  http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  http.get(`*/api/runs/${RUN_ID}/claims/c3`, () => HttpResponse.json(claimProvenance)),
];

it("shows the title, status and tabs for a completed run, with the claim in the URL", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "findings_open", iteration: 2 })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({
        ...reportJson,
        metadata: {
          ...reportJson.metadata,
          status: "findings_open",
          open_findings: ["icd203.tc.8@1"],
        },
      }),
    ),
    ...tabHandlers,
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review?claim=c3&tab=sources`);
  expect(await screen.findByRole("heading", { name: reportJson.title })).toBeInTheDocument();
  expect(screen.getByText("1 standard not met").closest(".pill")).toBeInTheDocument();
  expect(banner()).toHaveTextContent("Ready to review. 1 standard not met.");
  expect(screen.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("tab", { name: "Standards" }));
  expect(router.state.location.search).toBe("?claim=c3&tab=audit");
  expect(banner()).not.toHaveTextContent("Delivered without a full check");
}, 15_000);

it("sends the analyst to the progress screen while the run is not complete", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByText("This report has not been written yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "See its progress" })).toHaveAttribute(
    "href",
    `/runs/${RUN_ID}`,
  );
});

it("shows a report fetch failure inline", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () =>
      HttpResponse.json({ detail: "the database is unavailable: refused" }, { status: 503 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    ...tabHandlers,
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("alert")).toHaveTextContent("database is unavailable");
});

it("a run that does not exist says the report was not found and offers a new one (CRL-130)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json({ detail: `run ${RUN_ID} not found` }, { status: 404 }),
    ),
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("heading", { name: "Report not found" })).toBeInTheDocument();
  expect(screen.getByText(/does not exist, or it was deleted/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Start a new report" })).toHaveAttribute("href", "/new");
  expect(screen.queryByRole("alert")).toBeNull();
  await waitFor(() => expect(document.title).toBe("Report not found – Corelata"));
});

it("keeps the error line when the run cannot be read for another reason (CRL-130)", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 }),
    ),
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("alert")).toHaveTextContent("the database is unavailable");
  expect(screen.queryByRole("heading", { name: "Report not found" })).toBeNull();
});

it("selects a claim from the report, opens provenance, and pluralises open findings", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "findings_open" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({
        ...reportJson,
        metadata: {
          ...reportJson.metadata,
          status: "findings_open",
          open_findings: ["a@1", "b@1"],
        },
      }),
    ),
    ...tabHandlers,
    // selecting c1 opens the Provenance tab, which reads it
    http.get(`*/api/runs/${RUN_ID}/claims/c1`, () =>
      HttpResponse.json({ ...claimProvenance, claim: reportJson.claims[0]! }),
    ),
  );
  const { router } = renderApp(`/runs/${RUN_ID}/review?tab=audit`);
  await waitFor(() => expect(banner()).toHaveTextContent("2 standards not met."));
  const frame = (await screen.findByTitle("Report")) as HTMLIFrameElement;
  expect(frame.getAttribute("srcdoc")).toContain('p data-claim-ids="c1"');
  act(() => {
    const event = new MessageEvent("message", {
      data: { type: "corelata:select", claim: "c1" },
    });
    Object.defineProperty(event, "source", { value: frame.contentWindow });
    window.dispatchEvent(event);
  });
  await waitFor(() => expect(router.state.location.search).toBe("?tab=provenance&claim=c1"));
}, 15_000);

it("selecting a claim in the Provenance tab puts it in the URL", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    ...tabHandlers,
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  const list = await screen.findByRole("list", { name: "Claims" });
  await user.click(within(list).getAllByRole("button")[1]!);
  await waitFor(() => expect(router.state.location.search).toBe("?claim=c3"));
  expect(await screen.findByRole("list", { name: "Evidence for claim c3" })).toBeInTheDocument();
}, 15_000);

it("shows a failed report.json on the header and falls back to a plain title", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1 })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({ detail: "report.json unavailable" }, { status: 500 }),
    ),
    ...tabHandlers,
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("heading", { name: "Report" })).toBeInTheDocument();
  // The Provenance tab reports the same failure below; the header's alert comes first.
  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("report.json unavailable");
});

it("lists what did not complete when the report was delivered degraded", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "findings_open" })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json(degradedReportJson),
    ),
    ...tabHandlers,
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await waitFor(() =>
    expect(banner()).toHaveTextContent(
      "Delivered without a full check. The standards check didn't finish after 2 attempts.",
    ),
  );
  // the engine's error stays under Details (M18 spec §4.1)
  const details = within(banner()).getByText("Details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByRole("listitem")).toHaveTextContent(
    AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2),
  );
  expect(screen.getByText("Checked in part")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Standards" }));
  // the notice's reason is its own element, marked as the engine's text
  const notice = await screen.findByText(
    (_, el) =>
      el?.tagName === "P" &&
      el.textContent ===
        "The standards check didn't finish: auditor: invalid output after repair: " +
          "findings.icd203.as.1: Field required",
  );
  expect(notice).toBeInTheDocument();
  expect(notice.querySelector("[data-raw-error]")).toHaveTextContent(
    "auditor: invalid output after repair: findings.icd203.as.1: Field required",
  );
}, 15_000);

function serveReview(json = reportJson) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: json.metadata.status })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(json)),
    ...tabHandlers,
  );
}

it("leads back to the project, names the tab, and has Accept as its one primary button", async () => {
  serveReview();
  renderApp(`/runs/${RUN_ID}/review`);
  const main = screen.getByRole("main");
  await within(main).findByRole("heading", { name: reportJson.title });
  const crumb = within(main).getByRole("navigation", { name: "Breadcrumb" });
  expect(within(crumb).getByRole("link", { name: project.name })).toHaveAttribute(
    "href",
    `/new?project=${project.id}`,
  );
  expect(within(main).getByText("Meets the standards").closest(".pill")).toBeInTheDocument();
  expect(visiblePrimaryButtons(main)).toHaveLength(1);
  expect(within(main).getByRole("button", { name: "Accept" })).toHaveClass("primary");
  expect(
    within(main)
      .getAllByRole("tab")
      .map((tab) => tab.textContent),
  ).toEqual(["Claims", "Standards", "Process", "Sources"]);
  await waitFor(() => expect(document.title).toBe(`${reportJson.title} – Corelata`));
});

describe("a checked report (CRL-94)", () => {
  function serveCheck() {
    serveReview();
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(
          runProgress({
            state: "completed",
            status: "clean",
            kind: "check",
            report_source_id: "s-report",
            value_statement: "",
            max_iterations: 0,
          }),
        ),
      ),
    );
  }

  it("hides Accept, Return and the writing timeline, and offers the standards sheet", async () => {
    serveCheck();
    const { user } = renderApp(`/runs/${RUN_ID}/review?tab=process`);
    const main = screen.getByRole("main");
    await within(main).findByRole("heading", { name: reportJson.title });
    expect(within(main).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(main).queryByRole("button", { name: "Return with note…" })).toBeNull();
    expect(
      within(main)
        .getAllByRole("tab")
        .map((tab) => tab.textContent),
    ).toEqual(["Claims", "Standards", "Sources"]);
    // a Process link falls back to Claims
    expect(screen.getByRole("tab", { name: "Claims" })).toHaveAttribute("aria-selected", "true");
    expect(
      within(main).getByText(/written outside Corelata, checked against the standards/),
    ).toBeInTheDocument();
    await user.click(within(main).getByRole("button", { name: "Download" }));
    expect(screen.getByRole("menuitem", { name: "Standards sheet (CSV)" })).toHaveAttribute(
      "href",
      `/api/runs/${RUN_ID}/exports/findings.csv`,
    );
  });

  it("keeps the Claims, Standards and Sources tabs working, in plain words", async () => {
    serveCheck();
    const { user } = renderApp(`/runs/${RUN_ID}/review?claim=c3`);
    const main = screen.getByRole("main");
    await within(main).findByRole("list", { name: "Evidence for claim c3" });
    expectNoEngineWords(main);
    await user.click(screen.getByRole("tab", { name: "Standards" }));
    await within(main).findByRole("list", { name: "Met and not applicable" });
    expectNoEngineWords(main);
    await user.click(screen.getByRole("tab", { name: "Sources" }));
    expect(screen.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
  }, 15_000);
});

it("opens the standards not met from the banner", async () => {
  serveReview({
    ...reportJson,
    metadata: { ...reportJson.metadata, status: "findings_open", open_findings: ["icd203.tc.8@1"] },
  });
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await screen.findByRole("status", { name: "Where the review stands" });
  await user.click(await within(banner()).findByRole("button", { name: "Show them" }));
  expect(router.state.location.search).toBe("?tab=audit");
  expect(screen.getByRole("tab", { name: "Standards" })).toHaveAttribute("aria-selected", "true");
});

it("shows no engine word in the header, the banner, the claims and the standards (M18 spec §4)", async () => {
  serveReview();
  const { user } = renderApp(`/runs/${RUN_ID}/review?claim=c3`);
  const main = screen.getByRole("main");
  await within(main).findByRole("list", { name: "Evidence for claim c3" });
  expectNoEngineWords(main);
  await user.click(screen.getByRole("tab", { name: "Standards" }));
  await within(main).findByRole("list", { name: "Met and not applicable" });
  expectNoEngineWords(main);
}, 15_000);

// R-M18-27: the screen's "not met" is the engine's open_findings, the latest blocking and major
// fails; a minor fail leaves the report clean and is listed under Minor issues.
function servePlainWords(severity: "major" | "minor") {
  const rule = { ...resolvedPack.rules[0]!, id: "icd203.as.4", title: "Plain words", severity };
  const plain = {
    ...findings[1]!,
    rule_id: rule.id,
    verdict: "fail" as const,
    severity,
    evidence: "Paragraph 2 uses jargon.",
  };
  const open = severity === "minor" ? [] : [`${rule.id}@1`];
  serveReview({
    ...reportJson,
    metadata: {
      ...reportJson.metadata,
      status: open.length > 0 ? "findings_open" : "clean",
      open_findings: open,
    },
  });
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([...findings, plain])),
    http.get("*/api/packs/icd203-base/resolved", () =>
      HttpResponse.json({ ...resolvedPack, rules: [...resolvedPack.rules, rule] }),
    ),
  );
}

it("calls a report with only a minor fail clean, says so, and lists it under Minor issues", async () => {
  servePlainWords("minor");
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  const main = screen.getByRole("main");
  await within(main).findByRole("heading", { name: reportJson.title });
  expect(within(main).getByText("Meets the standards").closest(".pill")).toBeInTheDocument();
  await waitFor(() =>
    expect(banner()).toHaveTextContent(
      "Ready to review. Every blocking and major standard that could be checked was met. " +
        "1 minor issue is listed under Standards.",
    ),
  );
  await user.click(screen.getByRole("tab", { name: "Standards" }));
  const minor = await within(main).findByRole("list", { name: "Minor issues" });
  expect(within(minor).getByRole("listitem")).toHaveTextContent("Plain words");
  expect(within(minor).getByRole("listitem")).toHaveTextContent("Minor");
  expect(within(main).queryByRole("list", { name: "Not met" })).toBeNull();
  expectNoEngineWords(main);
}, 15_000);

it("lists a major fail under Not met and counts it in the banner", async () => {
  servePlainWords("major");
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  const main = screen.getByRole("main");
  await within(main).findByRole("heading", { name: reportJson.title });
  expect(within(main).getByText("1 standard not met").closest(".pill")).toBeInTheDocument();
  expect(banner()).toHaveTextContent("Ready to review. 1 standard not met.");
  await user.click(screen.getByRole("tab", { name: "Standards" }));
  const notMet = await within(main).findByRole("list", { name: "Not met" });
  // the tab's Not met group is the same set as the banner's count
  expect(within(notMet).getAllByRole("listitem")).toHaveLength(1);
  expect(within(notMet).getByRole("listitem")).toHaveTextContent("Plain words");
  expect(within(main).queryByRole("list", { name: "Minor issues" })).toBeNull();
}, 15_000);

describe("a returned run whose rerun is being written follows the rerun's stream (CRL-77)", () => {
  const RERUN = "77777777-7777-7777-7777-777777777777";
  let reads: number;
  let review: ReviewState;

  beforeEach(() => {
    reads = 0;
    review = {
      decision: "returned",
      at: "2026-10-13T10:10:00Z",
      actor: "ana",
      child_run_id: RERUN,
      child_state: null,
      child_error: null,
      note: "n",
    };
    FakeEventSource.instances = [];
    setEventSourceFactory((url) => new FakeEventSource(url));
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () => {
        reads += 1;
        return HttpResponse.json(runProgress({ state: "completed", status: "clean", review }));
      }),
      http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
      http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
      ...tabHandlers,
    );
    // Only the timers TanStack Query polls with: msw and React keep their own scheduling.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  });
  afterEach(() => {
    vi.useRealTimers();
    setEventSourceFactory(undefined);
  });

  const after = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
  const rerun = (state: RunState) =>
    runProgress({ run_id: RERUN, state, status: state === "completed" ? "clean" : null });

  async function open() {
    renderApp(`/runs/${RUN_ID}/review`);
    await after(0);
    await vi.waitFor(() =>
      expect(banner()).toHaveTextContent("The revised report is being written."),
    );
    expect(reads).toBe(1);
  }

  it("reads the run nothing while the rerun streams, and once when it ends", async () => {
    await open();
    const source = FakeEventSource.last();
    expect(source.url).toContain(`/runs/${RERUN}/events`);
    await after(10 * POLL_MS);
    act(() => source.emit("progress", rerun("drafting")));
    await after(10 * POLL_MS);
    expect(reads).toBe(1);
    review = { ...review, child_state: "completed" };
    act(() => source.emit("progress", rerun("completed")));
    await vi.waitFor(() => expect(reads).toBe(2));
    expect(source.closed).toBe(true);
    await vi.waitFor(() => expect(banner()).not.toHaveTextContent("is being written"));
    await after(10 * POLL_MS);
    expect(reads).toBe(2);
  });

  it("reads the run once when the rerun is deleted, and polls while it still says pending", async () => {
    await open();
    act(() => FakeEventSource.last().emit("deleted", {}));
    await vi.waitFor(() => expect(reads).toBe(2));
    // the run still names a rerun being written: no stream follows it now, so the page polls
    await after(POLL_MS);
    await vi.waitFor(() => expect(reads).toBe(3));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("polls when the stream fails", async () => {
    await open();
    act(() => FakeEventSource.last().fail());
    await after(POLL_MS);
    await vi.waitFor(() => expect(reads).toBe(2));
    await after(POLL_MS);
    await vi.waitFor(() => expect(reads).toBe(3));
  });

  it("polls without EventSource", async () => {
    setEventSourceFactory(null);
    await open();
    await after(POLL_MS);
    await vi.waitFor(() => expect(reads).toBe(2));
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});

describe("the value statement (CRL-101)", () => {
  function serveCompleted(value_statement: string) {
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(runProgress({ state: "completed", status: "clean", value_statement })),
      ),
      http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
      http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
      ...tabHandlers,
    );
  }

  it("shows what was asked for in the header, under the title", async () => {
    const statement = runProgress().value_statement;
    serveCompleted(statement);
    renderApp(`/runs/${RUN_ID}/review`);
    await screen.findByRole("heading", { name: reportJson.title });
    const header = screen.getByRole("heading", { name: reportJson.title }).closest("header")!;
    const shown = within(header).getByRole("region", { name: "Value statement" });
    expect(within(shown).getByText(statement)).toHaveAttribute("dir", "auto");
    // a short statement needs no fold
    expect(within(shown).queryByRole("button")).toBeNull();
    await screen.findByRole("list", { name: "Claims" });
    expectNoEngineWords(screen.getByRole("main"));
  });

  it("folds a statement longer than three lines, and opens it", async () => {
    fakeOverflow();
    serveCompleted(LONG_STATEMENT);
    const { user } = renderApp(`/runs/${RUN_ID}/review`);
    const shown = await screen.findByRole("region", { name: "Value statement" });
    const text = within(shown).getByText(LONG_STATEMENT);
    const fold = within(shown).getByRole("button", { name: "Show the whole statement" });
    expect(fold).toHaveAttribute("aria-controls", text.id);
    expect(text).toHaveAttribute("data-folded");
    await user.click(fold);
    expect(text).not.toHaveAttribute("data-folded");
    await user.click(within(shown).getByRole("button", { name: "Show less" }));
    expect(text).toHaveAttribute("data-folded");
    await screen.findByRole("list", { name: "Claims" });
  });
});

describe("a revised report (CRL-102)", () => {
  /** The revised report, completed, and its original as `parent` answers (a Response for a
   * failure). */
  function serveRevision(parent: Response | ReturnType<typeof returnedParent>) {
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(
          runProgress({ state: "completed", status: "clean", parent_run_id: PARENT_RUN_ID }),
        ),
      ),
      http.get(`*/api/runs/${PARENT_RUN_ID}`, () =>
        parent instanceof Response ? parent : HttpResponse.json(parent),
      ),
      http.get(`*/api/runs/${PARENT_RUN_ID}/exports/report.json`, () =>
        HttpResponse.json(parentReportJson),
      ),
      http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
      ...tabHandlers,
    );
  }

  const header = () => screen.getByRole("heading", { name: reportJson.title }).closest("header")!;

  it("says it is a revision, links the original's review by its title, and shows the note", async () => {
    serveRevision(returnedParent());
    renderApp(`/runs/${RUN_ID}/review`);
    await screen.findByRole("heading", { name: reportJson.title });
    const original = screen.getByRole("region", { name: "Original report" });
    expect(header()).toContainElement(original);
    const link = await within(original).findByRole("link", { name: parentReportJson.title });
    expect(link).toHaveAttribute("href", `/runs/${PARENT_RUN_ID}/review`);
    expect(link.closest("p")).toHaveTextContent(`Revision of ${parentReportJson.title}`);
    const note = await within(original).findByRole("region", { name: "Note for the writer" });
    expect(within(note).getByText(RETURN_NOTE)).toHaveAttribute("dir", "auto");
    await screen.findByRole("list", { name: "Claims" });
    expectNoEngineWords(screen.getByRole("main"));
  });

  it("shows no note, and no link, when the original is gone", async () => {
    const held = deferred();
    serveRevision(HttpResponse.json({ detail: "run not found" }, { status: 404 }));
    let asked = false;
    server.use(
      http.get(`*/api/runs/${PARENT_RUN_ID}`, async () => {
        asked = true;
        await held.promise;
        return HttpResponse.json({ detail: "run not found" }, { status: 404 });
      }),
    );
    renderApp(`/runs/${RUN_ID}/review`);
    const original = await screen.findByRole("region", { name: "Original report" });
    await waitFor(() => expect(asked).toBe(true));
    // no link to it while it is being read, only to take it back
    expect(within(original).queryByRole("link")).toBeNull();
    held.resolve();
    await waitFor(() =>
      expect(original).toHaveTextContent(
        "Revision of an earlier report that is no longer available.",
      ),
    );
    expect(within(original).queryByRole("link")).toBeNull();
    expect(within(original).queryByText(RETURN_NOTE)).toBeNull();
    expectNoEngineWords(screen.getByRole("main"));
  });

  it("shows no note when the original's decision is no longer the return that made it", async () => {
    serveRevision(
      returnedParent({ review: { decision: "accepted", at: "2026-10-13T11:00:00Z", note: "" } }),
    );
    renderApp(`/runs/${RUN_ID}/review`);
    const original = await screen.findByRole("region", { name: "Original report" });
    expect(
      await within(original).findByRole("link", { name: parentReportJson.title }),
    ).toBeInTheDocument();
    expect(within(original).queryByRole("region", { name: "Note for the writer" })).toBeNull();
  });

  it("says nothing of an original on a report that is not a revision", async () => {
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () =>
        HttpResponse.json(runProgress({ state: "completed", status: "clean" })),
      ),
      http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
      ...tabHandlers,
    );
    renderApp(`/runs/${RUN_ID}/review`);
    await screen.findByRole("list", { name: "Claims" });
    expect(screen.queryByRole("region", { name: "Original report" })).toBeNull();
    expect(screen.queryByText(/Revision of/)).toBeNull();
  });
});
