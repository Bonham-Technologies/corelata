import { useEffect, useId, useRef, type ReactNode } from "react";

/** A native modal dialog. Focus moves to the first button when it opens (or to the element whose
 * id is `initialFocusId`, as when a required field is inside) and back to whatever had it when it
 * closes. While `busy`, the confirm button reads `busyLabel` (CRL-43: "Returning…"), so a slow
 * request shows that something is happening. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busyLabel,
  cancelLabel = "Keep going",
  danger = false,
  busy = false,
  confirmDisabled = false,
  initialFocusId,
  restoreFocus = true,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  confirmDisabled?: boolean;
  initialFocusId?: string;
  /** Give focus back to the opener on close; false when the caller moves it elsewhere. */
  restoreFocus?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal();
      const first = initialFocusId ? document.getElementById(initialFocusId) : null;
      (first && dialog.contains(first)
        ? first
        : dialog.querySelector<HTMLElement>("button")
      )?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (restoreFocus) (opener.current as HTMLElement | null)?.focus?.();
    }
  }, [open, initialFocusId, restoreFocus]);
  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        // Escape while a request is in flight must not close (and so reset) the dialog.
        if (busy) event.preventDefault();
        else onCancel();
      }}
    >
      <h2 id={titleId}>{title}</h2>
      {children}
      <div className="row end">
        {/* The plain shared button is the neutral action; primary and danger mark the others. */}
        <button type="button" onClick={onCancel} disabled={busy}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={danger ? "danger" : "primary"}
          onClick={onConfirm}
          disabled={busy || confirmDisabled}
        >
          {busy && busyLabel ? busyLabel : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
