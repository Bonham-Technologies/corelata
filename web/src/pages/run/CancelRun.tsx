import { useState } from "react";
import { useCancelRun } from "../../api/runs";
import type { RunProgress } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";

/** M18 spec §5.3: Stop writing…, after a confirmation; the run stops at its next stage. A run
 * whose worker died after the first press never reaches that stage: once the server says the
 * worker is gone (`worker_gone`, CRL-49), the cancel is offered again and ends the run at once;
 * without a press, a run whose worker is gone offers it as Stop now… too (CRL-69). */
export function CancelRun({ runId, progress }: { runId: string; progress: RunProgress }) {
  const cancel = useCancelRun(runId);
  const [open, setOpen] = useState(false);
  if (progress.cancel_requested && !progress.worker_gone) {
    return (
      <p role="status" className="muted">
        Stopping after the current step…
      </p>
    );
  }
  return (
    <>
      {progress.cancel_requested && progress.worker_gone ? (
        <p role="status" className="muted">
          The process writing this report stopped responding, so it can't stop on its own.
        </p>
      ) : null}
      <button type="button" className="danger" onClick={() => setOpen(true)}>
        {progress.worker_gone ? "Stop now…" : "Stop writing…"}
      </button>
      {cancel.error ? <ErrorMessage error={cancel.error} /> : null}
      <ConfirmDialog
        open={open}
        title="Stop this report?"
        confirmLabel="Stop"
        busyLabel="Stopping…"
        danger
        busy={cancel.isPending}
        onConfirm={() => cancel.mutate(undefined, { onSettled: () => setOpen(false) })}
        onCancel={() => setOpen(false)}
      >
        <p>
          {progress.worker_gone
            ? "It stops now; no report will be produced."
            : "It stops after the step in progress; no report will be produced."}
        </p>
      </ConfirmDialog>
    </>
  );
}
