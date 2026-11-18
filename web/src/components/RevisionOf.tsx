import { Link } from "react-router";
import { ApiError } from "../api/client";
import { useReportJson } from "../api/reports";
import { useEarlierRun } from "../api/runs";
import { StatementShown } from "./StatementShown";

/** On a revised report (a run with `parent_run_id`), the report it revises and the note that
 * asked for it (CRL-102), both read from the original as the API serves it. The original is named
 * by its report's title, or "the original report" when it has none or it can't be read; its link
 * goes to its review, or to its outcome when it has no report. The line waits, its height held,
 * until the original and its title are read, so it never shows a name or a link it then takes
 * back. When the original is gone (404) the line still says it is a revision, without a link or a
 * note. The note shows only while the original's decision is the return that made this report. */
export function RevisionOf({ runId, parentRunId }: { runId: string; parentRunId: string }) {
  const parent = useEarlierRun(parentRunId);
  const original = parent.data;
  const hasReport = original?.state === "completed";
  const report = useReportJson(parentRunId, hasReport);
  const gone = parent.error instanceof ApiError && parent.error.status === 404;
  const settled = !parent.isPending && !(hasReport && report.isPending);
  const review = original?.review;
  const note =
    review?.decision === "returned" && review.child_run_id === runId ? review.note : null;
  const href = original && !hasReport ? `/runs/${parentRunId}` : `/runs/${parentRunId}/review`;
  return (
    <section aria-label="Original report" className="revision-of">
      {!settled ? (
        <p aria-hidden="true">{"\u00a0"}</p>
      ) : gone ? (
        <p>Revision of an earlier report that is no longer available.</p>
      ) : (
        <p>
          Revision of{" "}
          <Link to={href} dir="auto">
            {report.data?.title ?? "the original report"}
          </Link>
        </p>
      )}
      {settled && note ? (
        <StatementShown statement={note} label="Note for the writer" more="Show the whole note" />
      ) : null}
    </section>
  );
}
