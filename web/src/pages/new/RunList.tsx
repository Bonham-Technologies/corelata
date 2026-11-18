import { useId } from "react";
import { Link } from "react-router";
import { useRuns } from "../../api/projects";
import type { RunSummary } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { StatusText } from "../../components/StatusText";
import { whenText } from "../../lib/dates";
import { formatDateTime, isTerminal } from "../../lib/format";
import { fromSummary, runStatus } from "../../lib/status";

function OpenLink({ run }: { run: RunSummary }) {
  if (run.state === "completed") return <Link to={`/runs/${run.run_id}/review`}>Review</Link>;
  return <Link to={`/runs/${run.run_id}`}>{isTerminal(run.state) ? "Outcome" : "Progress"}</Link>;
}

/** The project page's Reports card (M18 spec §5.2): newest first, paged by cursor as before.
 * `onUse` takes a row's statement for the next report (CRL-84). */
export function RunList({
  projectId,
  onUse,
}: {
  projectId: string;
  onUse: (statement: string) => void;
}) {
  const runs = useRuns(projectId);
  const ids = useId();
  const rows = runs.data?.pages.flatMap((page) => page.runs) ?? [];
  if (runs.error && rows.length === 0) return <ErrorMessage error={runs.error} />;
  if (rows.length === 0) return null;
  return (
    <section aria-label="Reports" className="card">
      <h2>Reports</h2>
      <ul aria-label="Reports" className="report-list">
        {rows.map((run) => (
          <li key={run.run_id} className="report-row">
            <time dateTime={run.created_at} title={formatDateTime(run.created_at)}>
              {whenText(run.created_at)}
            </time>
            <span className="statement clamped" title={run.value_statement}>
              {/* a revised report is marked apart from its statement, which describes the
                  row's Use this statement button (CRL-102) */}
              {run.parent_run_id ? <span className="muted">Revised report · </span> : null}
              <span id={`${ids}-${run.run_id}`} dir="auto">
                {run.value_statement}
              </span>
            </span>
            <StatusText status={runStatus(fromSummary(run))} />
            <OpenLink run={run} />
            {/* described by its statement: in a list of the page's buttons, each says which */}
            <button
              type="button"
              className="link"
              aria-describedby={`${ids}-${run.run_id}`}
              onClick={() => onUse(run.value_statement)}
            >
              Use this statement
            </button>
          </li>
        ))}
      </ul>
      {/* a failed next page (or refresh) keeps the rows shown; Show more tries again */}
      {runs.error ? <ErrorMessage error={runs.error} /> : null}
      {runs.hasNextPage ? (
        <button type="button" disabled={runs.isFetching} onClick={() => void runs.fetchNextPage()}>
          Show more
        </button>
      ) : null}
    </section>
  );
}
