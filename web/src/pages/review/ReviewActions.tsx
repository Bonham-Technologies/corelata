import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { exportUrl, reportUrl } from "../../api/client";
import { rerunFreed, useReview, useReviewMarks } from "../../api/runs";
import type { ReviewMarks, ReviewState } from "../../api/types";
import { CharCount, nearLimit } from "../../components/CharCount";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Menu } from "../../components/Menu";
import { NOTE_MAX_LENGTH } from "../../lib/limits";
import { plural } from "../../lib/words";

/** "2 of 5 claims checked" (CRL-139): what the reviewer checked, shown before Accept. */
export function checkedText(marks: ReviewMarks): string {
  return `${marks.checked} of ${plural(marks.claims, "claim")} checked`;
}

/** The key-judgment claims not yet checked, when the team's profile requires them all checked
 * before Accept (CRL-139). */
export function stillToCheck(marks: ReviewMarks): string[] {
  const checked = new Set(marks.marks.filter((m) => m.mark === "checked").map((m) => m.claim_id));
  return marks.key_judgment_claim_ids.filter((id) => !checked.has(id));
}

/** The Download menu's items (M18 spec §5.4): today's four URLs, with plain names, and for a
 * checked report its standards sheet (CRL-94). */
export function downloads(runId: string, checked = false): [string, string][] {
  return [
    ["Word document (DOCX)", reportUrl(runId, "docx", { download: true })],
    ["Markdown", reportUrl(runId, "md", { download: true })],
    ["Web page (HTML)", reportUrl(runId, "html", { download: true })],
    ...(checked
      ? [["Standards sheet (CSV)", exportUrl(runId, "findings.csv")] as [string, string]]
      : []),
    ["Trace (JSON)", exportUrl(runId, "trace.json")],
  ];
}

/** The review header's actions (M18 spec §5.4): Accept, Return with note…, Download ▾. The
 * button rules are M9–M16's: both off while a request is out or once decided, on again when the
 * revision a return made ended without a report (R-M15-4), the note offered again then. */
export function ReviewActions({
  runId,
  review,
  onAccepted,
  checked = false,
}: {
  runId: string;
  review: ReviewState | null;
  /** A finished report written elsewhere and checked as it is (CRL-94): nothing to accept or
   * return, so only Download shows. */
  checked?: boolean;
  /** Called once the server has taken an Accept, so the page can move focus to its banner. */
  onAccepted?: () => void;
}) {
  const send = useReview(runId);
  const marks = useReviewMarks(runId, !checked).data;
  const disputed = marks?.disputed ?? 0;
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const acceptedHere = useRef(false);
  const [note, setNote] = useState("");
  const noteId = useId();
  const countId = useId();
  const busy = send.isPending;
  const freed = rerunFreed(review); // R-M15-4: Return and Accept are offered again
  const decided = review !== null && !freed;

  /** Accept is final (CRL-127), so the button only asks; this sends it once confirmed. On success
   * the dialog closes, and only then does the page move focus to the banner: while a modal dialog
   * is open the page behind it is inert and cannot take focus. */
  function accept() {
    send.mutate(
      { action: "accept", note: "" },
      {
        onSuccess: () => {
          acceptedHere.current = true;
          setConfirming(false);
        },
      },
    );
  }

  // The dialog is a child, so its effect (which closes it) has run by the time this one does.
  useEffect(() => {
    if (confirming || !acceptedHere.current) return;
    acceptedHere.current = false;
    onAccepted?.();
  });

  function sendReturn() {
    send.mutate(
      { action: "return", note: note.trim() },
      {
        onSuccess: (result) => {
          setOpen(false);
          setNote("");
          if (result.child) navigate(`/runs/${result.child.run_id}`);
        },
      },
    );
  }

  return (
    <div className="row review-actions">
      {checked ? null : (
        <>
          <button
            type="button"
            className="primary"
            onClick={() => {
              send.reset();
              setConfirming(true);
            }}
            disabled={busy || decided}
          >
            Accept
          </button>
          <button
            type="button"
            onClick={() => {
              send.reset();
              if (freed && !note) setNote(review?.note ?? "");
              setOpen(true);
            }}
            disabled={busy || decided}
          >
            Return with note…
          </button>
          {marks ? <span className="muted">{checkedText(marks)}</span> : null}
        </>
      )}
      <Menu label="Download" button="Download ▾">
        {(close) =>
          downloads(runId, checked).map(([name, href]) => (
            <a key={href} role="menuitem" href={href} onClick={close}>
              {name}
            </a>
          ))
        }
      </Menu>
      {send.error && !open && !confirming ? <ErrorMessage error={send.error} /> : null}
      <ConfirmDialog
        open={confirming}
        title="Accept this report?"
        confirmLabel="Accept report"
        busyLabel="Accepting…"
        cancelLabel="Cancel"
        busy={busy}
        confirmDisabled={decided}
        onConfirm={accept}
        onCancel={() => {
          send.reset();
          setConfirming(false);
        }}
      >
        {confirming && send.error ? <ErrorMessage error={send.error} /> : null}
        <p>
          This is final. The report can't be returned afterwards, and it will be used as project
          memory.
        </p>
        {marks ? (
          <p>
            {checkedText(marks)}
            {disputed ? `, ${disputed} disputed` : ""}.
          </p>
        ) : null}
        {marks?.require_key_judgments_checked ? (
          <p className="muted">
            Your team checks every claim a key judgment rests on, and leaves none disputed, before
            accepting.
            {stillToCheck(marks).length
              ? ` Still to check: ${stillToCheck(marks).join(", ")}.`
              : ""}
          </p>
        ) : null}
      </ConfirmDialog>
      <ConfirmDialog
        open={open}
        title="Return the report to the writer"
        confirmLabel="Return"
        busyLabel="Returning…"
        cancelLabel="Cancel"
        busy={busy}
        confirmDisabled={!note.trim() && disputed === 0}
        initialFocusId={noteId}
        onConfirm={sendReturn}
        onCancel={() => {
          send.reset();
          setOpen(false);
        }}
      >
        {send.error ? <ErrorMessage error={send.error} /> : null}
        <p className="muted">The note becomes guidance for the revised report.</p>
        {disputed ? (
          <p className="muted">
            {plural(disputed, "disputed claim")} {disputed === 1 ? "goes" : "go"} to the writer with
            your comments.
          </p>
        ) : null}
        {note.trim() || disputed ? null : <p className="muted">A note is required.</p>}
        <div className="field">
          <label htmlFor={noteId}>Note for the writer</label>
          <textarea
            id={noteId}
            rows={4}
            value={note}
            dir="auto"
            maxLength={NOTE_MAX_LENGTH}
            aria-describedby={nearLimit(note, NOTE_MAX_LENGTH) ? countId : undefined}
            onChange={(e) => setNote(e.target.value)}
          />
          <CharCount id={countId} value={note} max={NOTE_MAX_LENGTH} />
        </div>
      </ConfirmDialog>
    </div>
  );
}
