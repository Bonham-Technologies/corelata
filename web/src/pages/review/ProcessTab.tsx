import { useTrace } from "../../api/reports";
import type { DraftChanges, PriorReport } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { formatDateTime, formatDuration, formatInt } from "../../lib/format";
import { STEP_LABEL } from "../../lib/words";

export function describeChanges(changes: DraftChanges | null): string {
  if (changes === null) return "first draft";
  const parts: string[] = [];
  if (changes.title_changed) parts.push("title changed");
  if (changes.claims_added.length) parts.push(`added ${changes.claims_added.join(", ")}`);
  if (changes.claims_removed.length) parts.push(`removed ${changes.claims_removed.join(", ")}`);
  if (changes.claims_reworded.length) parts.push(`reworded ${changes.claims_reworded.join(", ")}`);
  if (changes.key_judgments_changed) parts.push("key judgments changed");
  if (changes.sections_changed.length)
    parts.push(`sections changed: ${changes.sections_changed.join(", ")}`);
  return parts.length ? parts.join("; ") : "no changes";
}

/** What became of an earlier accepted report the run was given (CRL-97). */
export function describePriorReport(report: PriorReport): string {
  if (report.cut) return "left out: over the token budget";
  const n = report.key_judgments.length;
  return `${n} key judgment${n === 1 ? "" : "s"} read`;
}

/** The earlier accepted reports of the project the writer and the auditor read, newest first
 * (CRL-97); nothing when the run read none. */
function PriorReports({ reports }: { reports: PriorReport[] | undefined }) {
  if (!reports?.length) return null;
  return (
    <>
      <h3>Earlier accepted reports</h3>
      <ul aria-label="Earlier accepted reports">
        {reports.map((r) => (
          <li key={r.run_id}>
            <code>{r.run_id}</code> {r.title} · accepted {formatDateTime(r.accepted_at)} ·{" "}
            {describePriorReport(r)}
          </li>
        ))}
      </ul>
    </>
  );
}

/** A stage in the reader's words with the engine's in brackets (M18 spec §4.4); a stage the
 * app does not know stays as it is. */
export function stageName(stage: string): string {
  const word = (STEP_LABEL as Record<string, string | undefined>)[stage];
  return word ? `${word} (${stage})` : stage;
}

export function ProcessTab({ runId }: { runId: string }) {
  const trace = useTrace(runId);
  if (trace.isPending) return <Loading what="Loading the trace" />;
  if (trace.error) return <ErrorMessage error={trace.error} />;
  const { summary, drafts } = trace.data!;
  const usage = summary.usage;
  return (
    <div className="process">
      <table aria-label="Stage timeline">
        <thead>
          <tr>
            <th>Stage</th>
            <th>Iteration</th>
            <th>Duration</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {summary.stages.map((s, i) => (
            <tr key={i}>
              <td>{stageName(s.stage)}</td>
              <td>{s.iteration}</td>
              <td>{formatDuration(s.duration_ms)}</td>
              <td>{s.ok ? "ok" : <span className="error">{s.error ?? "failed"}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <PriorReports reports={summary.prior_reports} />
      <h3>Drafts</h3>
      <ol aria-label="Drafts">
        {drafts.map((d, i) => (
          <li key={i}>
            {d.role}, iteration {d.iteration}: {describeChanges(d.changes)}
          </li>
        ))}
      </ol>
      <h3>Model usage</h3>
      <p className="muted">
        {formatInt(usage.calls)} model calls · {formatInt(usage.tokens_in)} tokens in ·{" "}
        {formatInt(usage.tokens_out)} out
      </p>
      <table aria-label="Token usage by role">
        <thead>
          <tr>
            <th>Role</th>
            <th>Calls</th>
            <th>Tokens in</th>
            <th>Tokens out</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(usage.by_role).map(([role, u]) => (
            <tr key={role}>
              <td>{role}</td>
              <td>{formatInt(u["calls"] ?? 0)}</td>
              <td>{formatInt(u["tokens_in"] ?? 0)}</td>
              <td>{formatInt(u["tokens_out"] ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
