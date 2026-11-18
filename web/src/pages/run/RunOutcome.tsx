import { Link } from "react-router";
import { useTrace } from "../../api/reports";
import type { RunProgress } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { StatementShown } from "../../components/StatementShown";
import { startFromLink, type StartFromState } from "../../lib/startFrom";
import { reportStatusText } from "../../lib/words";

/** `again`: the new-report page filled from this run (CRL-84). */
function GateReasons({ runId, again }: { runId: string; again: string }) {
  const trace = useTrace(runId);
  const gate = trace.data?.summary.gate;
  if (trace.error) return <ErrorMessage error={trace.error} />;
  if (!gate) return null;
  return (
    <div>
      <ul>
        {gate.reasons.map((reason, i) => (
          <li key={i} dir="auto">
            {reason}
          </li>
        ))}
      </ul>
      {gate.suggested_scope ? (
        <>
          <p>
            <strong>Suggested scope:</strong> <span dir="auto">{gate.suggested_scope}</span>
          </p>
          <p>
            <Link
              to={again}
              state={{ statement: gate.suggested_scope } satisfies StartFromState}
              className="button"
            >
              Use the suggested scope
            </Link>
          </p>
        </>
      ) : null}
    </div>
  );
}

/** M18 spec §5.3: what a finished run means for the analyst, and the one way on. */
export function outcomeHeading(progress: RunProgress): string | null {
  switch (progress.state) {
    case "completed":
      return "Ready to review.";
    case "gate_rejected":
      return "Not supported by the sources.";
    case "failed":
      return "This report couldn't be written.";
    case "cancelled":
      return "Stopped before the report was written.";
    default:
      return null;
  }
}

function completedText(progress: RunProgress, open: number | undefined): string {
  // the pill, the tab title and this line share reportStatusText, so they cannot drift
  if (progress.status === "clean") return `${reportStatusText("clean", 0)}.`;
  if (open === undefined) return "Some standards are not met; they're listed under Standards.";
  const status = reportStatusText("findings_open", open);
  return open > 0
    ? `${status}; they're listed under Standards.`
    : `${status}: it was delivered without a full check.`;
}

/** `openFindings`: the delivered report's open rules, once its report.json has loaded. */
export function RunOutcome({
  progress,
  openFindings,
}: {
  progress: RunProgress;
  openFindings?: number;
}) {
  // every way on starts from this run's statement, sources and options (CRL-84)
  const again = startFromLink(progress.project_id, progress.run_id);
  switch (progress.state) {
    case "completed":
      return (
        <section aria-label="Outcome" className="outcome">
          <p>{completedText(progress, openFindings)}</p>
          {progress.cancel_requested ? (
            <p className="muted">
              A stop was asked for, but the report had already finished its last step, so it was
              delivered.
            </p>
          ) : null}
          {progress.export_error ? (
            <div data-raw-error>
              <ErrorMessage error={new Error(progress.export_error)} />
            </div>
          ) : null}
          <Link to={`/runs/${progress.run_id}/review`} className="button primary">
            Review the report
          </Link>
        </section>
      );
    case "gate_rejected":
      return (
        <section aria-label="Outcome" className="outcome">
          <p>The value check didn&apos;t find this in the sources.</p>
          {/* "this": the statement, directly above the reasons (CRL-101) */}
          <StatementShown statement={progress.value_statement} />
          <GateReasons runId={progress.run_id} again={again} />
          <Link to={again} className="button">
            Try another statement
          </Link>
        </section>
      );
    case "failed":
      return (
        <section aria-label="Outcome" className="outcome">
          {/* the engine's own error text, shown as it is (marked for the engine-word guard) */}
          <div data-raw-error>
            <ErrorMessage error={new Error(progress.error ?? "No reason was recorded.")} />
          </div>
          <Link to={again} className="button">
            Start a new report
          </Link>
        </section>
      );
    case "cancelled":
      return (
        <section aria-label="Outcome" className="outcome">
          <Link to={again} className="button">
            Start a new report
          </Link>
        </section>
      );
    default:
      return null;
  }
}
