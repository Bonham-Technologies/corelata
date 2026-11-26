import { useId, useState, type ReactNode } from "react";
import { useClaim, useReportJson } from "../../api/reports";
import { useMarkClaim, useReviewMarks } from "../../api/runs";
import type { ClaimMark, ReviewMark, ReviewMarks } from "../../api/types";
import { CharCount, nearLimit } from "../../components/CharCount";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { NOTE_MAX_LENGTH } from "../../lib/limits";
import { quoteSpans } from "../../lib/quotes";
import { CLAIM_KIND, CLAIM_MARK, citedByText, plural } from "../../lib/words";

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

/** "Checked by ana", "Disputed": a mark as the claim's review shows it. */
function markText(mark: ReviewMark): string {
  return `${CLAIM_MARK[mark.mark]}${mark.actor ? ` by ${mark.actor}` : ""}`;
}

/** The reviewer's mark on the selected claim (CRL-139): checked or disputed, with a comment. Once
 * the report is accepted (or returned) the mark only shows. Keyed on the claim, so its comment
 * starts from that claim's own. */
function ClaimReview({
  runId,
  claimId,
  marks,
}: {
  runId: string;
  claimId: string;
  marks: ReviewMarks;
}) {
  const current = marks.marks.find((m) => m.claim_id === claimId);
  const [comment, setComment] = useState(current?.comment ?? "");
  const send = useMarkClaim(runId);
  const commentId = useId();
  const countId = useId();
  const status = current ? markText(current) : "Not marked yet";
  function mark(value: ClaimMark) {
    send.mutate({ claimId, mark: value, comment: comment.trim() });
  }
  return (
    <section aria-label={`Your review of claim ${claimId}`} className="claim-review">
      <h3>Your review of claim {claimId}</h3>
      <p role="status">
        {status}
        {current?.comment && !marks.editable ? `: ${current.comment}` : ""}
      </p>
      {marks.editable ? (
        <>
          <div className="field">
            <label htmlFor={commentId}>Comment</label>
            <textarea
              id={commentId}
              rows={2}
              value={comment}
              dir="auto"
              maxLength={NOTE_MAX_LENGTH}
              aria-describedby={nearLimit(comment, NOTE_MAX_LENGTH) ? countId : undefined}
              onChange={(e) => setComment(e.target.value)}
            />
            <CharCount id={countId} value={comment} max={NOTE_MAX_LENGTH} />
          </div>
          <div className="row">
            {(["checked", "disputed"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={current?.mark === value}
                disabled={send.isPending}
                onClick={() => mark(value)}
              >
                {value === "checked" ? "Mark checked" : "Mark disputed"}
              </button>
            ))}
          </div>
          {send.error ? <ErrorMessage error={send.error} /> : null}
        </>
      ) : null}
    </section>
  );
}

/** The Claims tab (tab id `provenance`, M18 spec §5.4): the claims as rows, each with its review
 * mark (CRL-139), and the selected claim's passages with where the report cites it and the
 * reviewer's mark on it. A checked report (`reviewed` false, CRL-94) has no marks. */
export function ProvenanceTab({
  runId,
  selectedClaim,
  onSelectClaim,
  reviewed = true,
}: {
  runId: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
  reviewed?: boolean;
}) {
  const report = useReportJson(runId);
  const claim = useClaim(runId, selectedClaim);
  const marks = useReviewMarks(runId, reviewed);
  const markOf = (claimId: string) => marks.data?.marks.find((m) => m.claim_id === claimId);
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
                    markOf(c.id) ? CLAIM_MARK[markOf(c.id)!.mark] : null,
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
      {marks.error && reviewed ? <ErrorMessage error={marks.error} /> : null}
      {selectedClaim !== null && marks.data ? (
        <ClaimReview key={selectedClaim} runId={runId} claimId={selectedClaim} marks={marks.data} />
      ) : null}
    </div>
  );
}
