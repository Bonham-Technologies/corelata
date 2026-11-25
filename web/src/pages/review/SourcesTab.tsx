import { useReportJson, useTrace } from "../../api/reports";
import type { ReportSourceEntry, SourceStatement, SourceSummary } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { plural } from "../../lib/words";

/** What the Notes column says about a source: a Coglossa export's reliability tier (CRL-96),
 * whether it was summarised before drafting, and whether it was read from a scan (CRL-95). */
function notes(s: SourceSummary): string {
  const parts: string[] = [];
  if (s.reliability_tier) parts.push(`Coglossa reliability tier ${s.reliability_tier}`);
  if (s.digested) parts.push("summarised before drafting");
  if (s.ocr_pages > 0) parts.push(`text recovered by OCR (${plural(s.ocr_pages, "page")})`);
  return parts.join("; ");
}

/** What the Notes column flags about a source's text (CRL-137): passages that read as
 * instructions to an AI system, and passages the document hides from its reader, which the
 * trace keeps and no model read. */
function flags(s: SourceSummary): string[] {
  const out: string[] = [];
  if (s.suspect_units > 0) {
    out.push(`${plural(s.suspect_units, "passage")} read as instructions to an AI`);
  }
  if (s.hidden_units > 0) {
    out.push(`${plural(s.hidden_units, "hidden passage")} withheld from the models`);
  }
  return out;
}

/** A source reference's fields, in the order the report gives them (CRL-96). */
const REFERENCE_FIELDS = [
  ["descriptor", "Descriptor"],
  ["reliability_note", "Reliability"],
  ["date_of_information", "Date of information"],
  ["origin", "Origin"],
  ["access", "Access"],
] as const;

type ReferenceLine = { label: string; value: string; byAnalyst: boolean };

/** What the report says about a source, each value labelled by who gave it (CRL-138): the
 * analyst stated it, or the model inferred it from the text. Without a report, only what the
 * analyst stated. */
export function referenceLines(
  entry: ReportSourceEntry | undefined,
  stated: SourceStatement | undefined,
): ReferenceLine[] {
  return REFERENCE_FIELDS.flatMap(([field, label]) => {
    const own = stated?.[field] ?? "";
    const value = entry ? (entry[field] ?? "") : own;
    return value ? [{ label, value, byAnalyst: own !== "" && own === value }] : [];
  });
}

export function SourcesTab({ runId }: { runId: string }) {
  const trace = useTrace(runId);
  const completed = trace.data?.summary.state === "completed";
  const report = useReportJson(runId, completed);
  if (trace.isPending) return <Loading what="Loading sources" />;
  if (trace.error) return <ErrorMessage error={trace.error} />;
  const summary = trace.data!.summary;
  const entries = new Map((report.data?.sources ?? []).map((e) => [e.source_id, e]));
  return (
    <div className="sources-tab">
      <p className="muted">
        Standards pack {summary.pack_name} ({summary.pack_hash.slice(0, 12)})
        {summary.profile ? `, team profile ${summary.profile}` : ""}
      </p>
      <table aria-label="Sources">
        <thead>
          <tr>
            <th>Source</th>
            <th>Kind</th>
            <th>SHA-256</th>
            <th>Units</th>
            <th>Notes</th>
            <th>Source reference</th>
          </tr>
        </thead>
        <tbody>
          {summary.sources.map((s) => (
            <tr key={s.id}>
              <td dir="auto">
                {s.name} <span className="muted">({s.id})</span>
              </td>
              <td>
                {s.kind === "coglossa_export"
                  ? `Coglossa run ${s.coglossa_run_id ?? "?"}`
                  : s.format.toUpperCase()}
              </td>
              <td>
                <code title={s.sha256}>{s.sha256.slice(0, 12)}</code>
              </td>
              <td>
                {s.units} unit{s.units === 1 ? "" : "s"}
              </td>
              <td>
                {notes(s)}
                {flags(s).map((flag) => (
                  <span key={flag} className="badge source-flag">
                    {flag}
                  </span>
                ))}
              </td>
              <td>
                {referenceLines(entries.get(s.id), s.stated).map((line) => (
                  <div key={line.label} className="reference-line">
                    <span className="muted">{line.label}:</span>{" "}
                    <span dir="auto">{line.value}</span>{" "}
                    <span className={line.byAnalyst ? "badge stated" : "muted"}>
                      {line.byAnalyst ? "stated by analyst" : "inferred by model"}
                    </span>
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
