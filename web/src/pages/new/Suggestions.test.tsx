import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { DISCOVERY_STALLED } from "../../api/discoveries";
import type { DiscoveryView } from "../../api/types";
import {
  candidates,
  DEADLINE_MS,
  deadlineFor,
  DISCOVERY_ID,
  discoveryView,
  minutesAgo,
  source,
  START_DEADLINE_MS,
} from "../../test/fixtures";
import { discoveryRefetchInterval } from "../../test/poll";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { Suggestions } from "./Suggestions";

function serveView(view: DiscoveryView | { detail: string }, status = 200) {
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => HttpResponse.json(view, { status })),
  );
}

/** Answers each read with the next [view, seconds, deadline] answer: the view, created at
 * `created` with its `deadline_at` that many ms after `created` (`deadlineMs` when the answer
 * gives none; the server's default, 10 minutes), and a `Date` header that many seconds after
 * `created` (the server's clock). The last answer repeats. */
function serveSequence(
  created: string,
  answers: [DiscoveryView, number, number?][],
  deadlineMs = DEADLINE_MS,
): () => number {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      const [view, seconds, deadline] = answers[Math.min(served, answers.length - 1)]!;
      served += 1;
      const date = new Date(Date.parse(created) + seconds * 1000).toUTCString();
      return HttpResponse.json(
        {
          ...view,
          created_at: created,
          deadline_at: deadlineFor(created, deadline ?? deadlineMs),
        },
        { headers: { Date: date } },
      );
    }),
  );
  return () => served;
}

const WAITING = "Waiting for Corelata to start looking…";
const LOOKING = "Looking for value in the selected sources…";
const NOT_STARTED =
  "Discovery did not start within 60 minutes and was stopped: the worker was stopped or busy with runs. Start a new discovery.";
const NOT_FINISHED =
  "Discovery did not finish within 10 minutes and was stopped. Start a new discovery.";
/** `deadline_at` of a discovery the worker claimed `minutes` after it was created. */
const claimedAt = (minutes: number) => minutes * 60_000 + DEADLINE_MS;

it("says it waits for the worker until the worker starts the discovery (R-M17-28)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  serveSequence(created, [
    [discoveryView({ state: "created" }), 5, START_DEADLINE_MS],
    [discoveryView({ state: "running" }), 7, claimedAt(0)],
  ]);
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  const waiting = await screen.findByText(WAITING);
  expect(waiting).toHaveAttribute("role", "status"); // a polite live region
  expect(waiting).toHaveAccessibleName("Suggestions");
  expect(await screen.findByText(LOOKING, {}, { timeout: 5000 })).toHaveAttribute("role", "status");
  expect(screen.queryByText(WAITING)).not.toBeInTheDocument();
});

it("keeps asking about a queued discovery past 10 minutes, inside its start limit (R-M17-27)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  const served = serveSequence(created, [
    [discoveryView({ state: "created" }), 12 * 60, START_DEADLINE_MS],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByText(WAITING)).toBeInTheDocument();
  await waitFor(() => expect(served()).toBe(1));
  await waitFor(() => expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(1000));
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
});

it("a queued discovery the server fails at its start limit shows the server's reason (R-M17-27)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  serveSequence(created, [
    [discoveryView({ state: "created" }), 59 * 60 + 59, START_DEADLINE_MS],
    [discoveryView({ state: "failed", error: NOT_STARTED }), 60 * 60 + 1, START_DEADLINE_MS],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(NOT_STARTED);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("a discovery claimed at minute 9 is asked about to minute 19 and shows the work limit's reason (R-M17-27)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  const served = serveSequence(created, [
    [discoveryView({ state: "running" }), 9 * 60 + 1, claimedAt(9)],
    [discoveryView({ state: "running" }), 18 * 60 + 59, claimedAt(9)], // past 10 minutes old
    [discoveryView({ state: "failed", error: NOT_FINISHED }), 19 * 60 + 1, claimedAt(9)],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toHaveTextContent(NOT_FINISHED);
  expect(served()).toBe(3);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("shows the 10-minute fallback only once the server let a claimed discovery run past its deadline_at (R-M17-27)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  const served = serveSequence(created, [
    // claimed at minute 9: 1 s under its ceiling, deadline_at + 15 s
    [discoveryView({ state: "running" }), 19 * 60 + 14, claimedAt(9)],
    [discoveryView({ state: "running" }), 19 * 60 + 16, claimedAt(9)],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  await waitFor(() => expect(served()).toBe(1));
  expect(await screen.findByText(LOOKING)).toBeInTheDocument();
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(await screen.findByText(DISCOVERY_STALLED, {}, { timeout: 5000 })).toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
  expect(served()).toBe(2);
});

it("a discovery still running 10 minutes after it started says so and stops asking (R-M16-2)", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running", created_at: minutesAgo(11) }));
    }),
  );
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  const status = await screen.findByText(DISCOVERY_STALLED);
  expect(status).toHaveAttribute("role", "status"); // a polite live region
  expect(status).toHaveTextContent(
    "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.",
  );
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
  expect(served).toBe(1);
});

it("a discovery the server fails at its deadline shows the server's reason, without a reload (R-M17-1)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString(); // only the server's Date matters
  const reason =
    "Discovery did not finish within 20 minutes and was stopped. Start a new discovery.";
  // a 20-minute deadline: past 10 minutes the screen keeps asking, and shows the server's ending
  serveSequence(
    created,
    [
      [discoveryView({ state: "running" }), 19 * 60 + 59],
      [discoveryView({ state: "failed", error: reason }), 20 * 60 + 1], // the read that failed it
    ],
    20 * 60_000,
  );
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(reason);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("with the default 10-minute deadline, a discovery the server fails at it shows the server's reason (R-M17-1)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString(); // only the server's Date matters
  const reason =
    "Discovery did not finish within 10 minutes and was stopped. Start a new discovery.";
  serveSequence(created, [
    [discoveryView({ state: "running" }), 9 * 60 + 59],
    [discoveryView({ state: "failed", error: reason }), 10 * 60 + 1], // the read that failed it
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(reason);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("stops at the read that crosses the ceiling, and a later reload shows how it ended", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString(); // only the server's Date matters
  const served = serveSequence(created, [
    // the server did not end it at its deadline (a clock that is off): 1 s under the ceiling
    [discoveryView({ state: "running" }), 10 * 60 + 14],
    [discoveryView({ state: "running" }), 10 * 60 + 16],
  ]);
  const first = renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  await waitFor(() => expect(served()).toBe(1));
  expect(await screen.findByText("Looking for value in the selected sources…")).toBeInTheDocument();
  await waitFor(() => expect(discoveryRefetchInterval(first.queryClient, DISCOVERY_ID)).toBe(1000));
  expect(await screen.findByText(DISCOVERY_STALLED, {}, { timeout: 5000 })).toBeInTheDocument();
  expect(discoveryRefetchInterval(first.queryClient, DISCOVERY_ID)).toBe(false);
  expect(served()).toBe(2);
  first.queryClient.clear();

  // the worker finished after the page stopped asking: a reload reads it once and shows it
  serveSequence(created, [[discoveryView({ state: "completed", candidates }), 10 * 60 + 30]]);
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findAllByRole("list", { name: "Suggested value statements" })).toHaveLength(
    1,
  );
});

it("a discovery that ends on the read past the ceiling shows its result, not the message", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  serveSequence(created, [
    [discoveryView({ state: "running" }), 9 * 60 + 58],
    [discoveryView({ state: "completed", candidates }), 10 * 60 + 2],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  const list = await screen.findByRole(
    "list",
    { name: "Suggested value statements" },
    { timeout: 5000 },
  );
  expect(list.children).toHaveLength(2);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("a failed discovery older than the ceiling shows its error", async () => {
  serveView(discoveryView({ state: "failed", error: "no queued job", created_at: minutesAgo(30) }));
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no queued job");
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
});

it("says so when no value statement was found", async () => {
  serveView(discoveryView({ state: "completed", candidates: [] }));
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(
    await screen.findByText("No value statement was found in these sources."),
  ).toBeInTheDocument();
});

it("shows one passage in the singular and omits an empty note", async () => {
  serveView(
    discoveryView({
      state: "completed",
      candidates: [
        { text: "T", audience: "A", evidence: [`${source.id}/u1`], confidence_note: "" },
      ],
    }),
  );
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByText(/· 1 passage$/)).toBeInTheDocument();
});

it("treats a candidate without evidence as zero passages", async () => {
  serveView(
    discoveryView({
      state: "completed",
      candidates: [{ text: "T", audience: "A", confidence_note: "n" }],
    }),
  );
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByText(/· 0 passages$/)).toBeInTheDocument();
});

it("falls back to a generic message for a failure without text", async () => {
  serveView(discoveryView({ state: "failed" }));
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("No suggestions could be made.");
});

it("shows a request error", async () => {
  serveView({ detail: "no such discovery" }, 404);
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no such discovery");
});
