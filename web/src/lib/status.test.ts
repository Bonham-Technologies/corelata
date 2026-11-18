import type { RunState } from "../api/types";
import { project, runProgress, runSummary } from "../test/fixtures";
import {
  fromProgress,
  fromSummary,
  projectStatus,
  reportStatus,
  runStatus,
  type RunLike,
} from "./status";

const run = (
  state: RunState,
  decision: RunLike["decision"] = null,
  childState: RunState | null = null,
) => runStatus({ state, decision, childState });
const shown = (s: { symbol: string; text: string; tone: string }) =>
  `${s.symbol} ${s.text} (${s.tone})`.trim();

it("gives every report state its words, symbol and tone (spec §4.2)", () => {
  expect(shown(run("created"))).toBe("… waiting to start (busy)");
  for (const state of ["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]) {
    expect(shown(run(state as RunState))).toBe("… writing (busy)");
  }
  expect(shown(run("completed"))).toBe("● waiting for review (busy)");
  expect(shown(run("completed", "accepted"))).toBe("✓ accepted (ok)");
  expect(shown(run("completed", "returned"))).toBe("↺ returned (none)"); // revision being written
  expect(shown(run("completed", "returned", "completed"))).toBe("↺ returned (none)");
  for (const ended of ["failed", "cancelled", "gate_rejected"] as const) {
    // the revision ended without a report: to review again (R-M15-1)
    expect(shown(run("completed", "returned", ended))).toBe("● waiting for review (busy)");
  }
  expect(shown(run("gate_rejected"))).toBe("⚠ not supported by the sources (warn)");
  expect(shown(run("failed"))).toBe("! couldn't finish (bad)");
  expect(shown(run("cancelled"))).toBe("■ stopped (none)");
});

it("reads a run's progress and a run list row the same way", () => {
  const review = {
    decision: "returned" as const,
    at: "2026-10-20T10:00:00Z",
    child_state: "failed" as const,
  };
  expect(fromProgress(runProgress({ state: "completed", review }))).toEqual({
    state: "completed",
    decision: "returned",
    childState: "failed",
  });
  expect(fromProgress(runProgress())).toEqual({
    state: "created",
    decision: null,
    childState: null,
  });
  expect(
    fromSummary({ ...runSummary, review_decision: "returned", review_child_state: "failed" }),
  ).toEqual({ state: "completed", decision: "returned", childState: "failed" });
  expect(fromSummary(runSummary)).toEqual({ state: "completed", decision: null, childState: null });
});

const latest = (state: RunState, decision: "accepted" | "returned" | null = null) => ({
  run_id: "r",
  state,
  status: null,
  decision,
});

it("gives a project the first status that holds (spec §3.3)", () => {
  const p = (overrides: Partial<typeof project>) =>
    shown(projectStatus({ ...project, ...overrides }));
  expect(p({ reports_writing: 1, reports_to_review: 2, latest_run: latest("failed") })).toBe(
    "… writing (busy)",
  );
  expect(p({ reports_to_review: 2, latest_run: latest("failed") })).toBe(
    "● 2 waiting for review (busy)",
  );
  expect(p({ latest_run: latest("failed") })).toBe("! needs attention (bad)");
  expect(p({ latest_run: latest("gate_rejected") })).toBe("⚠ not supported (warn)");
  expect(p({ latest_run: latest("completed", "accepted") })).toBe("✓ accepted (ok)");
  expect(p({ latest_run: latest("cancelled") })).toBe("■ stopped (none)");
  expect(p({ latest_run: null })).toBe("no reports yet (none)");
  // anything else: the latest report's own status (R-M18-6)
  expect(p({ latest_run: latest("completed", "returned") })).toBe("↺ returned (none)");
});

it("puts a returned latest report back to review when its revision ended without a report", () => {
  const returned = (child_state: RunState | null) => ({
    ...latest("completed", "returned"),
    child_state,
  });
  const p = (child: RunState | null) =>
    shown(projectStatus({ ...project, latest_run: returned(child) }));
  expect(p(null)).toBe("↺ returned (none)");
  expect(p("completed")).toBe("↺ returned (none)");
  for (const ended of ["failed", "cancelled", "gate_rejected"] as const) {
    expect(p(ended)).toBe("● waiting for review (busy)");
  }
});

it("gives a delivered report's status pill its words and symbol (spec §4.1)", () => {
  expect(shown(reportStatus("clean", 0))).toBe("✓ Meets the standards (ok)");
  expect(shown(reportStatus("findings_open", 2))).toBe("✗ 2 standards not met (warn)");
  expect(shown(reportStatus("findings_open", 0))).toBe("⚠ Checked in part (warn)");
});
