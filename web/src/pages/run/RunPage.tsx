import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { isNotFound } from "../../api/client";
import { liveUpdatesAvailable, useRunEvents } from "../../api/events";
import { useProjects } from "../../api/projects";
import { useReportJson } from "../../api/reports";
import { useRun } from "../../api/runs";
import type { RunProgress } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { Loading } from "../../components/Loading";
import { ReportNotFound } from "../../components/NotFound";
import { RevisionOf } from "../../components/RevisionOf";
import { StatementShown } from "../../components/StatementShown";
import { isTerminal } from "../../lib/format";
import { fromProgress, runStatus } from "../../lib/status";
import { CancelRun } from "./CancelRun";
import { outcomeHeading, RunOutcome } from "./RunOutcome";
import { StageDetails, Steps } from "./StageTimeline";
import { UsageSummary } from "./UsageSummary";

/** M18 spec §3.4: the tab names what the report is waiting for. */
function tabTitle(progress: RunProgress | undefined, project: string, report: string | undefined) {
  if (!progress) return null;
  if (!isTerminal(progress.state)) return `Writing… – ${project}`;
  if (progress.state === "completed") return `✓ Ready to review – ${report ?? project}`;
  const status = runStatus(fromProgress(progress));
  return `${status.text[0]!.toUpperCase()}${status.text.slice(1)} – ${project}`;
}

/** M18 spec §5.3: the steps over the event stream (polling when there is none), the Details
 * fold, Stop writing…, and the outcome once the run ends. */
export function RunPage() {
  const { runId = "" } = useParams();
  const [failedRun, setFailedRun] = useState<string | null>(null);
  const streamFailed = failedRun === runId; // a failure belongs to the run it happened on
  const live = liveUpdatesAvailable() && !streamFailed;
  const run = useRun(runId, live);
  const progress = run.data;
  useActiveProject(progress?.project_id ?? null);
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === progress?.project_id);
  const report = useReportJson(runId, progress?.state === "completed");
  const missing = isNotFound(run.error, runId); // CRL-130: unknown, or deleted since; NotFound names the tab
  useDocumentTitle(
    missing ? null : tabTitle(progress, project?.name ?? "Corelata", report.data?.title),
  );
  const onStreamFailed = useCallback(() => setFailedRun(runId), [runId]);
  useRunEvents(
    runId,
    progress !== undefined && !isTerminal(progress.state) && live,
    onStreamFailed,
  );

  if (run.isPending) return <Loading what="Loading the report's progress" />;
  if (missing) return <ReportNotFound />;
  if (run.error) return <ErrorMessage error={run.error} />;
  if (!progress) return null;
  const done = isTerminal(progress.state);
  // CRL-101: the statement sits under the heading in every state. A rejection's outcome holds it
  // directly above the reasons it was not supported, so that outcome comes first instead.
  const rejected = progress.state === "gate_rejected";
  const outcome = (
    <RunOutcome progress={progress} openFindings={report.data?.metadata.open_findings.length} />
  );
  return (
    <article className="writing">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to={`/new?project=${progress.project_id}`}>{project?.name ?? "Project"}</Link>
      </nav>
      <h1>{done ? outcomeHeading(progress) : "Writing the report"}</h1>
      {progress.parent_run_id ? (
        <RevisionOf runId={runId} parentRunId={progress.parent_run_id} />
      ) : null}
      {rejected ? outcome : <StatementShown statement={progress.value_statement} />}
      <Steps progress={progress} />
      {done || (progress.worker_gone && progress.cancel_requested) ? null : (
        // CRL-69: no false reassurance while nothing is writing it. One live region whose text
        // changes, so the change is announced; with a cancel recorded, CancelRun says it can't
        // stop on its own (CRL-49).
        <p role="status" className="muted">
          {progress.worker_gone
            ? "The process writing this report stopped responding. The report starts over when " +
              "it is running again, or you can end it with Stop now…."
            : "This usually takes a few minutes. You can leave this page; it keeps going."}
        </p>
      )}
      {!live && !done ? (
        <p className="muted">Live updates are off; checking every few seconds.</p>
      ) : null}
      {done && !rejected ? outcome : null}
      <details className="details">
        <summary>Details</summary>
        <StageDetails progress={progress} />
        {progress.attempts > 1 ? (
          <p className="muted">
            Started {progress.attempts} times: an earlier try stopped and the report started over.
          </p>
        ) : null}
        <UsageSummary usage={progress.usage} />
      </details>
      {done ? null : <CancelRun runId={runId} progress={progress} />}
    </article>
  );
}
