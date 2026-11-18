import { useEffect, useRef } from "react";
import { runStatus, type RunLike } from "../lib/status";
import { PROGRESS_STEPS, STEP_LABEL, VERDICT } from "../lib/words";
import { Dialog } from "./Dialog";

/** What each report status means (spec §4.2), as the screens show it. */
const STATUSES: [RunLike, string][] = [
  [
    { state: "drafting", decision: null, childState: null },
    "Corelata is still writing it. You can leave the page.",
  ],
  [
    { state: "completed", decision: null, childState: null },
    "Written and waiting for your review.",
  ],
  [
    { state: "completed", decision: "accepted", childState: null },
    "You or a colleague accepted it.",
  ],
  [
    { state: "completed", decision: "returned", childState: null },
    "Returned with a note; a revised report replaces it.",
  ],
  [
    { state: "gate_rejected", decision: null, childState: null },
    "The value check didn't find the statement in the sources.",
  ],
  [
    { state: "failed", decision: null, childState: null },
    "Something went wrong; the “Writing the report” screen says what.",
  ],
  [
    { state: "cancelled", decision: null, childState: null },
    "Stopped before the report was written.",
  ],
];

const STEP_HELP: Record<(typeof PROGRESS_STEPS)[number], string> = {
  created: "the report waits its turn.",
  ingesting: "the sources are split into passages.",
  gating: "the value statement is checked against the sources.",
  drafting: "the writer drafts the assessment.",
  conveying: "the draft is edited for its reader.",
  auditing: "every standard is checked.",
  rendering: "the documents you can download are made.",
  completed: "the report is ready for you.",
};

/** Adapted from Coglossa's HelpDialog (M18 spec §5.6): Corelata's keys, statuses, steps and
 * standards results on one short page. It opens at the top: focus goes to the heading, which the
 * browser would otherwise give to Close at the bottom, scrolling the page down to it. */
export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // runs after Dialog's own effect has called showModal(), which focused the first button
    if (open) heading.current?.focus();
  }, [open]);
  return (
    <Dialog open={open} label="Help" onClose={onClose} className="dialog help">
      <h2 ref={heading} tabIndex={-1}>
        Help
      </h2>
      <h3>Keyboard</h3>
      <dl className="shortcuts">
        <dt>
          <kbd>?</kbd>
        </dt>
        <dd>Open this help</dd>
        <dt>
          <kbd>←</kbd> <kbd>→</kbd> <kbd>Home</kbd> <kbd>End</kbd>
        </dt>
        <dd>Move between the tabs of a review</dd>
        <dt>
          <kbd>Esc</kbd>
        </dt>
        <dd>Close a menu or a dialog</dd>
      </dl>
      <h3>What the statuses mean</h3>
      <ul>
        {STATUSES.map(([run, meaning]) => {
          const status = runStatus(run);
          return (
            <li key={status.text}>
              {status.symbol} {status.text}: {meaning}
            </li>
          );
        })}
      </ul>
      <h3>Writing a report</h3>
      <ol>
        {PROGRESS_STEPS.map((step) => (
          <li key={step}>
            {STEP_LABEL[step]}: {STEP_HELP[step]}
          </li>
        ))}
      </ol>
      <h3>The standards check</h3>
      <ul>
        <li>
          {VERDICT.pass.symbol} {VERDICT.pass.text} and {VERDICT.fail.symbol} {VERDICT.fail.text}:
          the report meets a standard, or does not.
        </li>
        <li>
          {VERDICT.not_applicable.symbol} {VERDICT.not_applicable.text}: the rule has nothing to
          check in this report.
        </li>
        <li>
          {VERDICT.attested.symbol} {VERDICT.attested.text}: an advisory rule a reader judges; the
          check records what it saw.
        </li>
        <li>
          Return with note: the note becomes guidance for a revised report, written from the same
          sources and statement.
        </li>
      </ul>
      <div className="row end">
        <button type="button" className="primary" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}
