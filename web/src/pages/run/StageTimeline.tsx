import type { RunProgress, StageResult } from "../../api/types";
import { durationBetween, formatDuration, isTerminal, STAGES, type Stage } from "../../lib/format";
import {
  CHECK_STEPS,
  plural,
  PROGRESS_STEPS,
  REVISED_STEPS,
  STEP_LABEL,
  type ProgressStep,
} from "../../lib/words";

export type StepStatus = "done" | "now" | "failed" | "pending";

/** M18 spec §5.3: a step's state as a symbol and a word, never colour alone. */
export const STEP_MARK: Record<StepStatus, { symbol: string; word: string }> = {
  done: { symbol: "✓", word: "done" },
  now: { symbol: "●", word: "now" },
  failed: { symbol: "!", word: "failed" },
  pending: { symbol: "○", word: "not yet" },
};

export type StepRow = {
  step: ProgressStep;
  label: string;
  status: StepStatus;
  /** "revision 1 of 2" on the step in progress of a revision (§4.3); empty otherwise */
  revision: string;
  attempts: StageResult[];
  /** a failed step's own recorded error, for the short line under it; empty otherwise */
  error: string;
};

function stageStatus(progress: RunProgress, stage: Stage, attempts: StageResult[]): StepStatus {
  const last = attempts.at(-1);
  if (progress.state === stage) return "now";
  if (last) return last.ok ? "done" : "failed";
  return "pending";
}

/** One row per step (spec §4.3): waiting to start, the six stages, ready to review. A stage is
 * now when it is the run's state; done when its last attempt succeeded; failed when its last
 * attempt failed; not yet otherwise. */
export function stepRows(progress: RunProgress): StepRow[] {
  const stages = progress.stages ?? [];
  const steps: readonly ProgressStep[] = progress.kind === "check" ? CHECK_STEPS : PROGRESS_STEPS;
  return steps.map((step) => {
    const attempts = stages.filter((s) => s.stage === step);
    let status: StepStatus;
    if (step === "created") {
      status = progress.state === "created" ? "now" : stages.length > 0 ? "done" : "pending";
    } else if (step === "completed") {
      status = progress.state === "completed" ? "done" : "pending";
    } else {
      status = stageStatus(progress, step, attempts);
    }
    const revision =
      status === "now" && progress.iteration > 0 && REVISED_STEPS.has(step)
        ? `revision ${progress.iteration} of ${progress.max_iterations}`
        : "";
    const error = status === "failed" ? (attempts.at(-1)?.error ?? "") : "";
    return { step, label: STEP_LABEL[step], status, revision, attempts, error };
  });
}

/** The ordered steps; the one in progress carries aria-current="step". */
export function Steps({ progress }: { progress: RunProgress }) {
  const live = !isTerminal(progress.state);
  return (
    <ol aria-label="Steps" className="steps">
      {stepRows(progress).map((row) => (
        <li
          key={row.step}
          data-status={row.status}
          aria-current={live && row.status === "now" ? "step" : undefined}
        >
          <span className="step-mark" aria-hidden="true">
            {STEP_MARK[row.status].symbol}
          </span>
          <span className="step-name">{row.label}</span>
          <span className="step-state">
            {STEP_MARK[row.status].word}
            {row.revision ? ` · ${row.revision}` : ""}
          </span>
          {row.error ? (
            // the engine's own error text, shown as it is; data-raw-error marks it for the
            // engine-word guard in tests
            <p className="step-error muted" dir="auto" data-raw-error>
              {row.error}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function stageLine(stage: Stage, attempts: StageResult[]): string {
  const last = attempts.at(-1)!;
  const ms = durationBetween(last.started_at, last.finished_at);
  const parts = [ms === null ? "" : formatDuration(ms)];
  if (attempts.length > 1) parts.push(`ran ${plural(attempts.length, "time")}`);
  if (!last.ok && last.error) parts.push(last.error);
  const text = parts.filter(Boolean).join(" · ");
  return text ? `${STEP_LABEL[stage]}: ${text}` : STEP_LABEL[stage];
}

/** The Details fold's stage lines (before M18 the timeline's text): duration, how many times a
 * stage ran, and a failed stage's error. */
export function StageDetails({ progress }: { progress: RunProgress }) {
  const stages = progress.stages ?? [];
  const lines = STAGES.map((stage) => [stage, stages.filter((s) => s.stage === stage)] as const)
    .filter(([, attempts]) => attempts.length > 0)
    .map(([stage, attempts]) => {
      const last = attempts.at(-1)!;
      return { line: stageLine(stage, attempts), raw: !last.ok && Boolean(last.error) };
    });
  if (lines.length === 0) return <p className="muted">Nothing has started yet.</p>;
  return (
    <ul aria-label="Stage details" className="stage-details">
      {lines.map(({ line, raw }) => (
        // a line that carries a stage's raw error is marked for the engine-word guard in tests
        <li key={line} dir="auto" data-raw-error={raw ? "" : undefined}>
          {line}
        </li>
      ))}
    </ul>
  );
}
