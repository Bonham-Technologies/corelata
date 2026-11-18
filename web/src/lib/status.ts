import type {
  ProjectView,
  ReportStatus,
  ReviewDecision,
  RunProgress,
  RunState,
  RunSummary,
} from "../api/types";
import { reportStatusText, WAITING_FOR_REVIEW } from "./words";

/** Copied from Coglossa's lib/status.ts (spec §2.2): the tone classes are base.css's `tone-*`. */
export type Tone = "ok" | "warn" | "busy" | "bad" | "none";
/** A status always carries words, and a symbol where it has one; never colour alone. */
export type Status = { text: string; symbol: string; tone: Tone };

/** What `runStatus` reads: the run's state, its stored decision, and how the revision a return
 * made ended (null while it runs). */
export type RunLike = {
  state: RunState;
  decision: ReviewDecision | null;
  childState: RunState | null;
};

export function fromProgress(run: RunProgress): RunLike {
  return {
    state: run.state,
    decision: run.review?.decision ?? null,
    childState: run.review?.child_state ?? null,
  };
}

export function fromSummary(run: RunSummary): RunLike {
  return {
    state: run.state,
    decision: run.review_decision ?? null,
    childState: run.review_child_state ?? null,
  };
}

/** A revision that ended this way produced no report: the run is to review again (R-M15-1). */
const FREED_BY: ReadonlySet<RunState> = new Set<RunState>(["gate_rejected", "failed", "cancelled"]);

const WRITING: Status = { text: "writing", symbol: "…", tone: "busy" };
const TO_REVIEW: Status = { text: WAITING_FOR_REVIEW, symbol: "●", tone: "busy" };

/** M18 spec §4.2: a report's status, for the sidebar, the project page and the writing page. */
export function runStatus(run: RunLike): Status {
  switch (run.state) {
    case "created":
      return { text: "waiting to start", symbol: "…", tone: "busy" };
    case "completed":
      if (run.decision === "accepted") return { text: "accepted", symbol: "✓", tone: "ok" };
      if (run.decision === "returned" && !(run.childState && FREED_BY.has(run.childState))) {
        return { text: "returned", symbol: "↺", tone: "none" };
      }
      return TO_REVIEW;
    case "gate_rejected":
      return { text: "not supported by the sources", symbol: "⚠", tone: "warn" };
    case "failed":
      return { text: "couldn't finish", symbol: "!", tone: "bad" };
    case "cancelled":
      return { text: "stopped", symbol: "■", tone: "none" };
    default:
      return WRITING;
  }
}

/** M18 spec §4.1: a delivered report's status pill on Review. */
export function reportStatus(status: ReportStatus, open: number): Status {
  const text = reportStatusText(status, open);
  if (status === "clean") return { text, symbol: "✓", tone: "ok" };
  return { text, symbol: open > 0 ? "✗" : "⚠", tone: "warn" };
}

/** M18 spec §3.3: a project's one status in the sidebar, the first condition that holds. */
export function projectStatus(project: ProjectView): Status {
  if (project.reports_writing > 0) return WRITING;
  if (project.reports_to_review > 0) {
    return { ...TO_REVIEW, text: `${project.reports_to_review} ${WAITING_FOR_REVIEW}` };
  }
  const latest = project.latest_run;
  if (latest === null) return { text: "no reports yet", symbol: "", tone: "none" };
  switch (latest.state) {
    case "failed":
      return { text: "needs attention", symbol: "!", tone: "bad" };
    case "gate_rejected":
      return { text: "not supported", symbol: "⚠", tone: "warn" };
    case "cancelled":
      return { text: "stopped", symbol: "■", tone: "none" };
    default:
      // accepted, or returned (R-M18-6): a revision that ended without a report puts the
      // report back to review, one still being written or written leaves it returned
      return runStatus({
        state: latest.state,
        decision: latest.decision ?? null,
        childState: latest.child_state ?? null,
      });
  }
}
