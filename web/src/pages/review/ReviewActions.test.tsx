import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { POLL_MS } from "../../api/runs";
import { deferred } from "../../test/deferred";
import type { ReviewState } from "../../api/types";
import { reportHtml, reportJson, RUN_ID, runProgress } from "../../test/fixtures";
import { runRefetchInterval } from "../../test/poll";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

const BANNER = "Where the review stands";
const banner = () => screen.getByRole("status", { name: BANNER });
/** The banner's sentence once it says `text` (it is on the page from the first render). */
const expectBanner = (text: string) => waitFor(() => expect(banner()).toHaveTextContent(text));

/** Accept is final (CRL-127): the button opens a dialog, and this confirms it. */
async function confirmAccept(user: ReturnType<typeof renderApp>["user"]) {
  await user.click(await screen.findByRole("button", { name: "Accept" }));
  const dialog = await screen.findByRole("dialog", { name: "Accept this report?" });
  await user.click(within(dialog).getByRole("button", { name: "Accept report" }));
}

function serveCompleted(overrides: Parameters<typeof runProgress>[0] = {}) {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({ state: "completed", status: "clean", iteration: 1, ...overrides }),
      ),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
  );
}

it("offers the four downloads in a menu, with plain names (M18 spec §5.4)", async () => {
  serveCompleted();
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Download" }));
  const menu = screen.getByRole("menu", { name: "Download" });
  const items = within(menu).getAllByRole("menuitem");
  expect(items.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Word document (DOCX)", `/api/runs/${RUN_ID}/report?format=docx&download=true`],
    ["Markdown", `/api/runs/${RUN_ID}/report?format=md&download=true`],
    ["Web page (HTML)", `/api/runs/${RUN_ID}/report?format=html&download=true`],
    ["Trace (JSON)", `/api/runs/${RUN_ID}/exports/trace.json`],
  ]);
  expect(items[0]).toHaveFocus(); // Coglossa's Menu: the first item takes focus
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull();
});

const accepted = {
  decision: "accepted" as const,
  at: "2026-10-15T10:00:00Z",
  actor: "ana",
  child_run_id: null,
};

it("accepts, then shows the server's decision and disables both actions (test_accept_and_conflict)", async () => {
  let decided = false;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({
          state: "completed",
          status: "clean",
          iteration: 1,
          review: decided ? accepted : null,
        }),
      ),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
  );
  let posted: unknown;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted = await request.json();
      decided = true;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await confirmAccept(user);
  await expectBanner("Accepted");
  expect(posted).toEqual({ action: "accept", note: "" });
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
});

it("a reload shows an accepted run as decided", async () => {
  serveCompleted({ review: accepted });
  renderApp(`/runs/${RUN_ID}/review`);
  await expectBanner("Accepted");
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: "Open the revised report" })).not.toBeInTheDocument();
});

it("a returned run shows the decision and links to the rerun", async () => {
  serveCompleted({
    review: {
      decision: "returned",
      at: "2026-10-15T10:00:00Z",
      actor: "ana",
      child_run_id: "77777777-7777-7777-7777-777777777777",
    },
  });
  renderApp(`/runs/${RUN_ID}/review`);
  await expectBanner("Returned");
  expect(screen.getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
    "href",
    "/runs/77777777-7777-7777-7777-777777777777",
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
});

it("shows a conflict when the run can no longer be reviewed", async () => {
  serveCompleted();
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () =>
      HttpResponse.json(
        { detail: `run ${RUN_ID} is failed; only a completed run can be reviewed` },
        { status: 409 },
      ),
    ),
  );
  const again = renderApp(`/runs/${RUN_ID}/review`);
  await confirmAccept(again.user);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "only a completed run can be reviewed",
  );
});

it("shows a failed return inside the open dialog and keeps the note", async () => {
  serveCompleted();
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () =>
      HttpResponse.json(
        { detail: `run ${RUN_ID} is failed; only a completed run can be reviewed` },
        { status: 409 },
      ),
    ),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "Fix it");
  await user.click(screen.getByRole("button", { name: "Return" }));
  const dialog = screen.getByRole("dialog");
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "only a completed run can be reviewed",
  );
  expect(dialog).toHaveAttribute("open");
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("Fix it");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Return with note…" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps Return disabled for a whitespace-only note", async () => {
  serveCompleted();
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "   ");
  expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
  expect(screen.getByText("A note is required.")).toBeInTheDocument();
});

it("returns with a note and opens the child run (test_return_requires_a_note_and_opens_the_child)", async () => {
  serveCompleted();
  const child = runProgress({
    run_id: "77777777-7777-7777-7777-777777777777",
    parent_run_id: RUN_ID,
  });
  let posted: unknown;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ action: "return", child });
    }),
    http.get(`*/api/runs/${child.run_id}`, () => HttpResponse.json(child)),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  const dialog = await screen.findByRole("dialog", { name: "Return the report to the writer" });
  const send = screen.getByRole("button", { name: "Return" });
  expect(send).toBeDisabled();
  expect(dialog).toHaveTextContent("The note becomes guidance for the revised report.");
  await user.type(
    screen.getByRole("textbox", { name: "Note for the writer" }),
    "Add the 2027 date",
  );
  await user.click(send);
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${child.run_id}`));
  expect(posted).toEqual({ action: "return", note: "Add the 2027 date" });
});

it("keeps the note through a failed return and clears it after one that succeeds", async () => {
  serveCompleted();
  const posted: unknown[] = [];
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted.push(await request.json());
      if (posted.length === 1) {
        return HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 });
      }
      // No child in the reply: the page stays, so the dialog can be opened again.
      return HttpResponse.json({ action: "return", child: null });
    }),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  await user.type(note, "Add the 2027 date");
  await user.click(screen.getByRole("button", { name: "Return" }));
  expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
    "the database is unavailable",
  );
  expect(note).toHaveValue("Add the 2027 date");
  await user.click(screen.getByRole("button", { name: "Return" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(posted).toEqual([
    { action: "return", note: "Add the 2027 date" },
    { action: "return", note: "Add the 2027 date" },
  ]);
  expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/review`);
  await user.click(screen.getByRole("button", { name: "Return with note…" }));
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("");
});

const RERUN = "77777777-7777-7777-7777-777777777777";

function returned(overrides: Partial<ReviewState> = {}): ReviewState {
  return {
    decision: "returned",
    at: "2026-10-18T10:00:00Z",
    actor: "ana",
    child_run_id: RERUN,
    child_state: null,
    child_error: null,
    note: "Add the 2027 date",
    ...overrides,
  };
}

it.each([
  [
    { child_state: "failed" as const, child_error: "could not queue the run: connection refused" },
    "The revised report couldn't be written: could not queue the run: connection refused. Return the report again or accept it.",
  ],
  [
    { child_state: "failed" as const },
    "The revised report couldn't be written: no reason was recorded. Return the report again or accept it.",
  ],
  [
    { child_state: "cancelled" as const },
    "The revised report was stopped; return the report again or accept it.",
  ],
  [
    { child_state: "gate_rejected" as const },
    "The revised report stopped at the value check (not supported by the sources); return the report again or accept it.",
  ],
])(
  "a return whose rerun ended without a report offers both actions again (%o)",
  async (fate, says) => {
    serveCompleted({ review: returned(fate) });
    renderApp(`/runs/${RUN_ID}/review`);
    await expectBanner("Returned");
    expect(banner()).toHaveTextContent(says);
    expect(screen.getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
      "href",
      `/runs/${RERUN}`,
    );
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Return with note…" })).toBeEnabled();
  },
);

it("a return whose rerun is live or completed keeps both actions off and says nothing more", async () => {
  for (const child_state of [null, "drafting" as const, "completed" as const]) {
    serveCompleted({ review: returned({ child_state }) });
    const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
    await expectBanner("Returned with a note.");
    expect(banner()).not.toHaveTextContent("again");
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
    queryClient.clear();
    cleanup();
  }
});

it("returns again after a failed rerun, offering the previous note (R-M15-4)", async () => {
  serveCompleted({ review: returned({ child_state: "failed", child_error: "model down" }) });
  const second = runProgress({
    run_id: "88888888-8888-4888-8888-888888888888",
    parent_run_id: RUN_ID,
  });
  let posted: unknown;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ action: "return", child: second });
    }),
    http.get(`*/api/runs/${second.run_id}`, () => HttpResponse.json(second)),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  expect(note).toHaveValue("Add the 2027 date");
  await user.type(note, " and the tariff");
  await user.click(screen.getByRole("button", { name: "Return" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${second.run_id}`));
  expect(posted).toEqual({ action: "return", note: "Add the 2027 date and the tariff" });
});

it("an open Review page keeps reading the run while its rerun runs, and shows its failure", async () => {
  let review = returned();
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1, review })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
  );
  const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
  await expectBanner("Returned with a note. The revised report is being written.");
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS); // a finished run, still read
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  review = returned({ child_state: "failed", child_error: "model down" });
  await act(() => queryClient.refetchQueries({ queryKey: ["runs", RUN_ID] }));
  await expectBanner("The revised report couldn't be written: model down.");
  expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
  expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false); // the rerun ended: no more reads
});

it("keeps a note the reviewer typed when Return is reopened after a cancel", async () => {
  serveCompleted({ review: returned({ child_state: "failed" }) });
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  await user.clear(note);
  await user.type(note, "My own words");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Return with note…" }));
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("My own words");
});

it("opens Return with an empty note when the failed return stored none", async () => {
  serveCompleted({ review: returned({ child_state: "failed", note: null }) });
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("");
});

it("locks the actions again once a second return is re-read with its rerun pending", async () => {
  let review = returned({ child_state: "failed", child_error: "model down" });
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1, review })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      review = returned({ child_state: null });
      return HttpResponse.json({ action: "return", child: null });
    }),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.click(screen.getByRole("button", { name: "Return" }));
  await waitFor(() => expect(banner()).not.toHaveTextContent("again"));
  expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/review`);
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
});

it.each([409, 503])(
  "re-reads the run after a refused review (%i) so a stale freed page locks, and keeps the message",
  async (status) => {
    let review = returned({ child_state: "failed", child_error: "model down" });
    let reads = 0;
    server.use(
      http.get(`*/api/runs/${RUN_ID}`, () => {
        reads += 1;
        return HttpResponse.json(
          runProgress({ state: "completed", status: "clean", iteration: 1, review }),
        );
      }),
      http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
      http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
      http.get(`*/api/runs/${RUN_ID}/trace`, () =>
        HttpResponse.json({ detail: "x" }, { status: 500 }),
      ),
      http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
      http.post(`*/api/runs/${RUN_ID}/review`, () => {
        review = returned({ child_state: null }); // the other reviewer's rerun is now live
        return HttpResponse.json({ detail: `run ${RUN_ID} was returned already` }, { status });
      }),
    );
    const { user } = renderApp(`/runs/${RUN_ID}/review`);
    await confirmAccept(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("was returned already");
    await waitFor(() => expect(banner()).not.toHaveTextContent("again"));
    expect(reads).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
  },
);

it("a stale page whose report another reviewer accepted shows the refusal, then the decision (R-M16-1)", async () => {
  let review: ReviewState | null = null; // this page loaded before the other reviewer accepted
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1, review })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      review = accepted;
      return HttpResponse.json(
        { detail: `run ${RUN_ID} was accepted; start a new run to change it` },
        { status: 409 },
      );
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "One more pass");
  await user.click(screen.getByRole("button", { name: "Return" }));
  expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
    "was accepted; start a new run to change it",
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await expectBanner("Accepted");
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
});

it("moves focus to the banner after Accept (M18 polish F1)", async () => {
  let decided = false;
  serveCompleted();
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({
          state: "completed",
          status: "clean",
          iteration: 1,
          review: decided ? accepted : null,
        }),
      ),
    ),
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      decided = true;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await confirmAccept(user);
  await expectBanner("Accepted");
  await waitFor(() => expect(banner()).toHaveFocus());
  expect(banner()).toHaveAttribute("tabindex", "-1");
});

it("opens the Return dialog with focus in the note field (M18 polish F3)", async () => {
  serveCompleted();
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveFocus();
});

it("says Returning… on the dialog's button while the return is out (CRL-43)", async () => {
  serveCompleted();
  const held = deferred();
  const child = runProgress({
    run_id: "77777777-7777-7777-7777-777777777777",
    parent_run_id: RUN_ID,
  });
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async () => {
      await held.promise;
      return HttpResponse.json({ action: "return", child });
    }),
    http.get(`*/api/runs/${child.run_id}`, () => HttpResponse.json(child)),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "Add a date");
  await user.click(screen.getByRole("button", { name: "Return" }));
  expect(await screen.findByRole("button", { name: "Returning…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  held.resolve();
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${child.run_id}`));
});

it("says Accepting… on the dialog's button while the accept is out (CRL-43, CRL-127)", async () => {
  serveCompleted();
  const held = deferred();
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async () => {
      await held.promise;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await confirmAccept(user);
  expect(await screen.findByRole("button", { name: "Accepting…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
  held.resolve();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
});

it("bounds the return note at the API's 8,000 characters and counts near the limit (CRL-83)", async () => {
  serveCompleted();
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  expect(note).toHaveAttribute("maxLength", "8000");
  fireEvent.change(note, { target: { value: "n".repeat(7199) } });
  expect(screen.queryByText(/of 8,000 characters/)).toBeNull();
  fireEvent.change(note, { target: { value: "n".repeat(8000) } });
  expect(note).toHaveAccessibleDescription("8,000 of 8,000 characters");
});

it("shows the server's refusal of a return past the guidance cap in the dialog (CRL-111)", async () => {
  const detail =
    "this report's returns would carry more than 24000 characters of writer guidance; start a new report with the guidance that still applies";
  serveCompleted();
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () => HttpResponse.json({ detail }, { status: 422 })),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "One more pass");
  await user.click(screen.getByRole("button", { name: "Return" }));
  const dialog = screen.getByRole("dialog");
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(detail);
  expect(dialog).toHaveAttribute("open");
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("One more pass");
});

it("asks before accepting and says the decision is final (CRL-127)", async () => {
  serveCompleted();
  let posts = 0;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      posts += 1;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Accept" }));
  const dialog = await screen.findByRole("dialog", { name: "Accept this report?" });
  expect(dialog).toHaveTextContent("can't be returned");
  expect(dialog).toHaveTextContent("project memory");
  expect(posts).toBe(0);
});

it("cancelling the Accept dialog records nothing and returns focus to Accept (CRL-127)", async () => {
  serveCompleted();
  let posts = 0;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      posts += 1;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  const accept = await screen.findByRole("button", { name: "Accept" });
  await user.click(accept);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog", { name: "Accept this report?" })).not.toBeInTheDocument();
  expect(accept).toHaveFocus();
  expect(posts).toBe(0);
  expect(banner()).toHaveTextContent(/./);
  expect(banner()).not.toHaveTextContent("Accepted");
});

it("Escape closes the Accept dialog without accepting (CRL-127)", async () => {
  serveCompleted();
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  const accept = await screen.findByRole("button", { name: "Accept" });
  await user.click(accept);
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(accept).toHaveFocus();
});

it("keeps the Accept dialog open with the refusal when the accept fails (CRL-127)", async () => {
  serveCompleted();
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () =>
      HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 }),
    ),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await confirmAccept(user);
  const dialog = screen.getByRole("dialog", { name: "Accept this report?" });
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("the database is unavailable");
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
