import { render, screen, within } from "@testing-library/react";
import { runProgress } from "../../test/fixtures";
import { StageDetails, stepRows, Steps } from "./StageTimeline";

const stage = (stage: string, iteration: number, ok = true, error: string | null = null) => ({
  stage,
  iteration,
  ok,
  error,
  output: null,
  started_at: "2026-10-13T10:02:00Z",
  finished_at: "2026-10-13T10:02:03Z",
});

it("derives one row per step from the recorded attempts and the current state", () => {
  const progress = runProgress({
    state: "auditing",
    iteration: 1,
    stages: [
      stage("ingesting", 0),
      stage("gating", 0),
      stage("drafting", 0),
      stage("conveying", 0),
      stage("auditing", 0),
      stage("drafting", 1),
      stage("conveying", 1),
    ],
  });
  expect(stepRows(progress).map((r) => [r.step, r.status, r.attempts.length, r.revision])).toEqual([
    ["created", "done", 0, ""],
    ["ingesting", "done", 1, ""],
    ["gating", "done", 1, ""],
    ["drafting", "done", 2, ""],
    ["conveying", "done", 2, ""],
    ["auditing", "now", 1, "revision 1 of 2"],
    ["rendering", "pending", 0, ""],
    ["completed", "pending", 0, ""],
  ]);
  const failed = runProgress({
    state: "failed",
    stages: [stage("ingesting", 0), stage("gating", 0, false, "model unreachable")],
  });
  expect(stepRows(failed).map((r) => r.status)).toEqual([
    "done",
    "done",
    "failed",
    "pending",
    "pending",
    "pending",
    "pending",
    "pending",
  ]);
  expect(stepRows(runProgress()).map((r) => r.status)).toEqual([
    "now",
    ...Array(7).fill("pending"),
  ]);
  expect(stepRows(runProgress({ state: "cancelled" }))[0]?.status).toBe("pending");
  const completed = stepRows(runProgress({ state: "completed", stages: [stage("rendering", 1)] }));
  expect(completed.at(-1)?.status).toBe("done");
  expect(completed.at(-2)?.status).toBe("done");
});

it("shows each step's state as a symbol and a word, and marks the current step", () => {
  render(
    <Steps
      progress={runProgress({
        state: "drafting",
        iteration: 1,
        stages: [stage("ingesting", 0), stage("gating", 0), stage("drafting", 0)],
      })}
    />,
  );
  const items = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem");
  expect(items).toHaveLength(8);
  expect(items[1]).toHaveTextContent("✓Reading the sourcesdone");
  expect(items[3]).toHaveTextContent("●Draftingnow · revision 1 of 2");
  expect(items[3]).toHaveAttribute("aria-current", "step");
  expect(items[7]).toHaveTextContent("○Ready to reviewnot yet");
  expect(items[7]).not.toHaveAttribute("aria-current");
  expect(items[1]!.querySelector(".step-mark")).toHaveAttribute("aria-hidden", "true");
});

it("marks a failed step, and no current step once the report has ended", () => {
  render(
    <Steps
      progress={runProgress({
        state: "failed",
        stages: [stage("ingesting", 0), stage("gating", 0, false, "model unreachable")],
      })}
    />,
  );
  const items = screen.getAllByRole("listitem");
  expect(items[2]).toHaveTextContent("!Checking the value statementfailed");
  expect(items.some((li) => li.hasAttribute("aria-current"))).toBe(false);
});

it("lists each stage's duration, how often it ran and a failed stage's error under Details", () => {
  const unfinished = { ...stage("gating", 0, false, "model unreachable"), finished_at: "" };
  const { rerender } = render(
    <StageDetails
      progress={runProgress({
        state: "failed",
        stages: [stage("ingesting", 0), stage("drafting", 0), stage("drafting", 1), unfinished],
      })}
    />,
  );
  const lines = within(screen.getByRole("list", { name: "Stage details" })).getAllByRole(
    "listitem",
  );
  expect(lines.map((li) => li.textContent)).toEqual([
    "Reading the sources: 3.0 s",
    "Checking the value statement: model unreachable",
    "Drafting: 3.0 s · ran 2 times",
  ]);
  expect(lines[1]).toHaveAttribute("dir", "auto");
  rerender(<StageDetails progress={runProgress({ stages: undefined })} />);
  expect(screen.getByText("Nothing has started yet.")).toBeInTheDocument();
  rerender(
    <StageDetails
      progress={runProgress({ stages: [{ ...stage("ingesting", 0), finished_at: "" }] })}
    />,
  );
  expect(screen.getByRole("listitem")).toHaveTextContent(/^Reading the sources$/);
});

it("shows a failed step's own error in a short line under the step", () => {
  render(
    <Steps
      progress={runProgress({
        state: "failed",
        error: "run failed elsewhere",
        stages: [stage("ingesting", 0), stage("gating", 0, false, "model unreachable")],
      })}
    />,
  );
  const items = screen.getAllByRole("listitem");
  const line = within(items[2]!).getByText("model unreachable");
  expect(line).toHaveClass("step-error");
  expect(line).toHaveAttribute("dir", "auto");
  expect(line).toHaveAttribute("data-raw-error");
  expect(screen.queryByText("run failed elsewhere")).toBeNull();
  expect(items[1]!.querySelector(".step-error")).toBeNull();
});

it("shows no error line for a failed step that recorded none", () => {
  render(
    <Steps
      progress={runProgress({ state: "failed", stages: [stage("ingesting", 0, false, null)] })}
    />,
  );
  expect(document.querySelector(".step-error")).toBeNull();
});

it("lists a check's own steps: reading the report, then the standards (CRL-94)", () => {
  const progress = runProgress({
    kind: "check",
    state: "auditing",
    max_iterations: 0,
    stages: [stage("ingesting", 0), stage("structuring", 0)],
  });
  expect(stepRows(progress).map((r) => [r.label, r.status])).toEqual([
    ["Waiting to start", "done"],
    ["Reading the sources", "done"],
    ["Reading the report", "done"],
    ["Checking against the standards", "now"],
    ["Preparing the documents", "pending"],
    ["Ready to review", "pending"],
  ]);
  render(<StageDetails progress={progress} />);
  expect(screen.getByText(/^Reading the report: /)).toBeInTheDocument();
});
