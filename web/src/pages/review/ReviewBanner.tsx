import { Fragment, type ReactNode, type Ref } from "react";
import { Link } from "react-router";
import { rerunFreed, rerunPending } from "../../api/runs";
import type { ReviewState } from "../../api/types";
import { formatDateTime } from "../../lib/format";
import { degradationText, plural } from "../../lib/words";

/** Why a returned report can be returned again (R-M15-4), in the reader's words. */
export function revisionOutcome(review: ReviewState): ReactNode {
  switch (review.child_state) {
    case "cancelled":
      return "The revised report was stopped; return the report again or accept it.";
    case "gate_rejected":
      return "The revised report stopped at the value check (not supported by the sources); return the report again or accept it.";
    default:
      return (
        <>
          The revised report couldn&apos;t be written:{" "}
          {review.child_error ? (
            <span data-raw-error>{review.child_error}</span>
          ) : (
            "no reason was recorded"
          )}
          . Return the report again or accept it.
        </>
      );
  }
}

function Revised({ review }: { review: ReviewState }) {
  if (!review.child_run_id) return null;
  return <Link to={`/runs/${review.child_run_id}`}>Open the revised report</Link>;
}

/** M18 spec §5.4's banner: one sentence on where the review stands, and the one thing to do
 * next. A decision decides it; without one, a stage delivered without, then the standards not
 * met, then a clean report (R-M18-12), which names its minor issues if it has any (R-M18-27). */
export function ReviewBanner({
  review,
  open,
  minor = 0,
  degradations,
  onShowStandards,
  bannerRef,
}: {
  review: ReviewState | null;
  open: number;
  /** Rules whose latest verdict is a minor fail: they leave the report clean (R-M18-27). */
  minor?: number;
  degradations: string[];
  onShowStandards: () => void;
  /** So the page can focus the banner after a decision; it is a target, not a control. */
  bannerRef?: Ref<HTMLElement>;
}) {
  let body;
  if (review?.decision === "accepted") {
    const by = review.actor ? ` by ${review.actor}` : "";
    body = (
      <p>
        Accepted{by} on {formatDateTime(review.at)}.
      </p>
    );
  } else if (review && rerunFreed(review)) {
    body = (
      <>
        <p dir="auto">Returned with a note. {revisionOutcome(review)}</p>
        <Revised review={review} />
      </>
    );
  } else if (review) {
    body = (
      <>
        <p>
          Returned with a note.
          {rerunPending(review) ? " The revised report is being written." : ""}
        </p>
        <Revised review={review} />
      </>
    );
  } else if (degradations.length > 0) {
    // a line in neither known form is the engine's own text, shown as it is and marked so
    const lines = degradations.map((line) => ({ ...degradationText(line), raw: line }));
    const details = lines.flatMap((line) => (line.detail ? [line.detail] : []));
    body = (
      <>
        <p dir="auto">
          Delivered without a full check.
          {lines.map((l, i) => (
            <Fragment key={i}>
              {" "}
              {l.text === l.raw ? <span data-raw-error>{l.text}</span> : l.text}
            </Fragment>
          ))}
        </p>
        {details.length > 0 ? (
          <details>
            <summary>Details</summary>
            <ul>
              {details.map((detail, i) => (
                <li key={i} dir="auto" data-raw-error>
                  {detail}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </>
    );
  } else if (open > 0) {
    body = (
      <>
        <p>Ready to review. {plural(open, "standard")} not met.</p>
        <button type="button" className="link" onClick={onShowStandards}>
          Show them
        </button>
      </>
    );
  } else if (minor > 0) {
    body = (
      <p>
        Ready to review. Every blocking and major standard that could be checked was met.{" "}
        {minor === 1 ? "1 minor issue is" : `${minor} minor issues are`} listed under Standards.
      </p>
    );
  } else {
    body = <p>Ready to review. Every standard that could be checked was met.</p>;
  }
  return (
    <section
      ref={bannerRef}
      tabIndex={-1}
      role="status"
      aria-label="Where the review stands"
      className="banner row"
    >
      {body}
    </section>
  );
}
