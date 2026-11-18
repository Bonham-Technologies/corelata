import { useTrace } from "../../api/reports";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { plural } from "../../lib/words";

/** What the Notes column says about a source: summarised, read from a scan (CRL-95), both. */
function notes(source: { digested: boolean; ocr_pages: number }): string {
  const out: string[] = [];
  if (source.digested) out.push("summarised before drafting");
  if (source.ocr_pages > 0) out.push(`text recovered by OCR (${plural(source.ocr_pages, "page")})`);
  return out.join("; ");
}

export function SourcesTab({ runId }: { runId: string }) {
  const trace = useTrace(runId);
  if (trace.isPending) return <Loading what="Loading sources" />;
  if (trace.error) return <ErrorMessage error={trace.error} />;
  const summary = trace.data!.summary;
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
              <td>{notes(s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
