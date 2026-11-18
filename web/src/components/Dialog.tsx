import { useEffect, useRef, type ReactNode } from "react";

type Props = {
  open: boolean;
  label: string;
  onClose: () => void;
  className?: string;
  children: ReactNode;
};

/** Copied from Coglossa (spec §2.2): a modal <dialog>. The browser traps focus; Esc asks onClose,
 * so a parent can refuse. Children render only while it is open. */
export function Dialog({ open, label, onClose, className = "dialog", children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-label={label}
      className={className}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open ? children : null}
    </dialog>
  );
}
