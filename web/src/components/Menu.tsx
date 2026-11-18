import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

type Props = {
  label: string;
  button: ReactNode;
  className?: string;
  children: (close: () => void) => ReactNode;
};

/** Copied from Coglossa (spec §2.2): a button that opens a list of actions; Esc or a click
 * outside closes it. */
export function Menu({ label, button, className, children }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  /** Close and hand focus back to the button, so a keyboard user is not left on nothing. */
  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };
  // Items an arrow key can land on: aria-disabled ones count (focusable, inert); disabled do not.
  const items = () =>
    Array.from(
      ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') ?? [],
    );
  useEffect(() => {
    if (open) items()[0]?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    // Escape with focus elsewhere (the container's own handler has already dealt with the rest).
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    const onPointer = (event: PointerEvent) => {
      if (ref.current?.contains(event.target as Node)) return;
      setOpen(false);
      // The press moves focus after this handler: to what was pressed, or to nothing. Only in
      // the second case does the button take it back.
      setTimeout(() => {
        if (document.activeElement === document.body) buttonRef.current?.focus();
      });
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);
  function onKeyDown(event: KeyboardEvent) {
    if (!open) return;
    if (event.key === "Escape") {
      // Only the menu: a dialog around it would otherwise cancel on the same key press.
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const to =
      event.key === "ArrowDown"
        ? (at + 1) % list.length
        : event.key === "ArrowUp"
          ? at <= 0 // from the first item, or from the button (-1), wrap to the last
            ? list.length - 1
            : at - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? list.length - 1
              : null;
    if (to === null || list.length === 0) return;
    event.preventDefault();
    list[to]?.focus();
  }
  return (
    <div
      ref={ref}
      className={className ? `menu ${className}` : "menu"}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        // Focus moved on to something outside: Tab out, or a click elsewhere. No related target
        // means the window lost focus, or a browser that does not focus buttons on click.
        const to = event.relatedTarget as Node | null;
        if (to && !ref.current?.contains(to)) setOpen(false);
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {button}
      </button>
      {open ? (
        <div id={id} role="menu" aria-label={label} className="menu-list">
          {/* Coglossa turns this rule off for the whole app; Corelata keeps it (R-M18-9). */}
          {/* eslint-disable-next-line react-hooks/refs -- close() reads the button's ref only when an item calls it, from an event handler (R-M18-9) */}
          {children(close)}
        </div>
      ) : null}
    </div>
  );
}
