import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ReviewState } from "../../api/types";
import { expectNoEngineWords } from "../../test/engine-words";
import { AUDIT_INCOMPLETE } from "../../test/fixtures";
import { ReviewBanner } from "./ReviewBanner";

const AT = "2026-10-20T10:00:00Z";
const REVISED = "77777777-7777-7777-7777-777777777777";

function show(
  props: Partial<Parameters<typeof ReviewBanner>[0]> & { review?: ReviewState | null } = {},
) {
  const onShowStandards = vi.fn();
  const element = (
    <ReviewBanner
      review={props.review ?? null}
      open={props.open ?? 0}
      minor={props.minor ?? 0}
      degradations={props.degradations ?? []}
      onShowStandards={onShowStandards}
    />
  );
  render(<RouterProvider router={createMemoryRouter([{ path: "/", element }])} />);
  return {
    banner: screen.getByRole("status", { name: "Where the review stands" }),
    onShowStandards,
  };
}

const returned = (child_state: ReviewState["child_state"] = null): ReviewState => ({
  decision: "returned",
  at: AT,
  actor: "ana",
  child_run_id: REVISED,
  child_state,
  child_error: null,
  note: "n",
});

it("says a clean report is ready", () => {
  expect(show().banner).toHaveTextContent(
    "Ready to review. Every standard that could be checked was met.",
  );
});

it("counts the standards not met and opens them", async () => {
  const { banner, onShowStandards } = show({ open: 2 });
  expect(banner).toHaveTextContent("Ready to review. 2 standards not met.");
  await userEvent.setup().click(within(banner).getByRole("button", { name: "Show them" }));
  expect(onShowStandards).toHaveBeenCalled();
});

it("says what was skipped, keeps the engine's error under Details, and shows an unknown line as it is", () => {
  const { banner } = show({
    degradations: [
      "conveyance skipped after 1 attempt: conveyor: bad JSON",
      AUDIT_INCOMPLETE,
      "new",
    ],
  });
  expect(banner).toHaveTextContent(
    "Delivered without a full check. Editing for the reader was skipped after 1 attempt. " +
      "The standards check didn't finish after 2 attempts. new",
  );
  const details = within(banner).getAllByRole("listitem");
  expect(details.map((li) => li.textContent)).toEqual([
    "conveyor: bad JSON",
    AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2),
  ]);
});

it("names who accepted and when, or only when", () => {
  const accepted: ReviewState = { decision: "accepted", at: AT, actor: "ana" };
  const when = new Date(AT).toLocaleString();
  expect(show({ review: accepted, open: 3 }).banner).toHaveTextContent(
    `Accepted by ana on ${when}.`,
  );
  cleanup();
  expect(show({ review: { ...accepted, actor: null } }).banner).toHaveTextContent(
    `Accepted on ${when}.`,
  );
});

it("says a returned report's revision is being written, or links to the written one", () => {
  const live = show({ review: returned() }).banner;
  expect(live).toHaveTextContent("Returned with a note. The revised report is being written.");
  expect(within(live).getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
    "href",
    `/runs/${REVISED}`,
  );
  cleanup();
  const done = show({ review: returned("completed") }).banner;
  expect(done).toHaveTextContent(/^Returned with a note\.Open the revised report$/);
  cleanup();
  const making = show({ review: { ...returned(), child_run_id: null } }).banner;
  expect(within(making).queryByRole("link")).toBeNull(); // the revision is still being made
});

it("says how a revision that produced no report ended", () => {
  const failed = show({ review: { ...returned("failed"), child_error: "model down" } }).banner;
  expect(failed).toHaveTextContent(
    "Returned with a note. The revised report couldn't be written: model down. Return the report again or accept it.",
  );
});

it("keeps engine words out of every banner but the engine's own error text", () => {
  const degraded = show({
    degradations: ["conveyance skipped after 1 attempt: conveyor: bad JSON", AUDIT_INCOMPLETE],
  }).banner;
  expectNoEngineWords(degraded, { exceptRawErrors: true });
  expect(() => expectNoEngineWords(degraded)).toThrow(); // the details carry the engine's words
  cleanup();
  const freed = show({
    review: { ...returned("failed"), child_error: "could not queue the run: refused" },
  }).banner;
  expectNoEngineWords(freed, { exceptRawErrors: true });
  expect(freed.querySelector("[data-raw-error]")).toHaveTextContent(
    "could not queue the run: refused",
  );
  cleanup();
  const unrecorded = show({ review: { ...returned("failed"), child_error: null } }).banner;
  expectNoEngineWords(unrecorded, { exceptRawErrors: true });
  expect(unrecorded).toHaveTextContent("no reason was recorded");
});

it("shows no Details when no skipped stage has an error to keep", () => {
  const { banner } = show({ degradations: ["conveyance skipped after 2 attempts"] });
  expect(banner).toHaveTextContent(
    "Delivered without a full check. Editing for the reader was skipped after 2 attempts.",
  );
  expect(within(banner).queryByText("Details")).toBeNull();
});

// R-M18-27: minor failures leave a report clean, as the engine has it; the banner says so.
it("says a clean report with minor issues meets every blocking and major standard", () => {
  expect(show({ minor: 2 }).banner).toHaveTextContent(
    "Ready to review. Every blocking and major standard that could be checked was met. " +
      "2 minor issues are listed under Standards.",
  );
  cleanup();
  expect(show({ minor: 1 }).banner).toHaveTextContent(
    "Ready to review. Every blocking and major standard that could be checked was met. " +
      "1 minor issue is listed under Standards.",
  );
  cleanup();
  // standards not met take the banner; the minor issues wait in the tab
  expect(show({ open: 1, minor: 1 }).banner).toHaveTextContent(
    /^Ready to review\. 1 standard not met\.Show them$/,
  );
});

it("marks an unrecognised degradation line as the engine's own text", () => {
  const { banner } = show({
    degradations: [AUDIT_INCOMPLETE, "writer digest skipped: audit window too small"],
  });
  const raw = within(banner).getByText("writer digest skipped: audit window too small");
  expect(raw).toHaveAttribute("data-raw-error");
  expect(raw.closest("p")).toHaveTextContent(
    "Delivered without a full check. The standards check didn't finish after 2 attempts. " +
      "writer digest skipped: audit window too small",
  );
  // our words around it pass the guard
  expectNoEngineWords(banner, { exceptRawErrors: true });
});
