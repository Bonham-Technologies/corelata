import type { ReactNode } from "react";
import { useClaim, useReportJson } from "../../api/reports";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { quoteSpans } from "../../lib/quotes";
import { CLAIM_KIND, citedByText, plural } from "../../lib/words";

/** A unit's text with the words the claim quotes from it marked (CRL-93). A quote the browser
 * cannot find marks nothing; with none found the whole unit reads as before quotes existed. */
function Passage({ text, quotes }: { text: string; quotes: string[] }) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const [start, end] of quoteSpans(text, quotes)) {
    parts.push(text.slice(at, start), <mark key={start}>{text.slice(start, end)}</mark>);
    at = end;
  }
  parts.push(text.slice(at));
  return <blockquote dir="auto">{parts}</blockquote>;
}

/** The Claims tab (tab id `provenance`, M18 spec §5.4): the claims as rows, and the selected
 * claim's passages with where the report cites it. */
export function ProvenanceTab({
  runId,
  selectedClaim,
  onSelectClaim,
}: {
  runId: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
}) {
  const report = useReportJson(runId);
  const claim = useClaim(runId, selectedClaim);
  return (
    <div className="provenance">
      {report.isPending ? <Loading what="Loading claims" /> : null}
      {report.error ? <ErrorMessage error={report.error} /> : null}
      {report.data ? (
        <ul aria-label="Claims" className="claims">
          {report.data.claims.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="claim"
                aria-pressed={c.id === selectedClaim}
                onClick={() => onSelectClaim(c.id)}
              >
                <span className="claim-id">{c.id}</span>
                <span dir="auto">{c.text}</span>
                <span className="muted claim-meta">
                  {[
                    CLAIM_KIND[c.kind],
                    c.likelihood_term,
                    plural((c.evidence ?? []).length, "passage"),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {selectedClaim === null ? (
        <p className="muted">Select a claim, here or in the report, to see its evidence.</p>
      ) : null}
      {selectedClaim !== null && claim.isPending ? <Loading what="Loading evidence" /> : null}
      {claim.error ? <ErrorMessage error={claim.error} /> : null}
      {claim.data ? (
        <section aria-label={`Evidence for claim ${selectedClaim}`} className="evidence">
          <h3>Evidence for claim {selectedClaim}</h3>
          <ul aria-label={`Evidence for claim ${selectedClaim}`}>
            {claim.data.evidence.map((u) => (
              <li key={u.ref}>
                <p className="muted">
                  <span dir="auto">{u.source_name}</span> · {u.locator}
                </p>
                <Passage
                  text={u.text}
                  quotes={(claim.data.claim.quotes ?? [])
                    .filter((q) => q.ref === u.ref)
                    .map((q) => q.text)}
                />
              </li>
            ))}
          </ul>
          <p className="muted">Cited in: {claim.data.cited_by.map(citedByText).join("; ")}</p>
        </section>
      ) : null}
    </div>
  );
}
