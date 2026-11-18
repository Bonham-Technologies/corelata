import { useId, useLayoutEffect, useRef, useState } from "react";

/** The value statement a report was asked for, labelled, on the pages that follow it (CRL-101).
 * Folded to three lines while it is longer; the fold is measured, so it shows only when the
 * statement runs past three lines at the width it is drawn at. Screen readers read it whole.
 * `label` and `more` let it show other text the same way, such as a revision's note (CRL-102). */
export function StatementShown({
  statement,
  label = "Value statement",
  more = "Show the whole statement",
}: {
  statement: string;
  label?: string;
  more?: string;
}) {
  const labelId = useId();
  const textId = useId();
  const text = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);

  // measured while folded: the clamp cuts the text short exactly when it is over three lines
  useLayoutEffect(() => {
    if (open) return;
    const el = text.current!;
    const measure = () => setLong(el.scrollHeight > el.clientHeight + 1);
    measure();
    // the bundled font can arrive after the first layout and wrap the text differently
    let current = true;
    void document.fonts?.ready.then(() => {
      if (current) measure();
    });
    window.addEventListener("resize", measure);
    return () => {
      current = false;
      window.removeEventListener("resize", measure);
    };
  }, [statement, open]);

  return (
    <section aria-labelledby={labelId} className="statement-shown">
      <p id={labelId} className="statement-label">
        {label}
      </p>
      <p
        ref={text}
        id={textId}
        dir="auto"
        className="statement-text"
        data-folded={!open || undefined}
      >
        {statement}
      </p>
      {long ? (
        <button
          type="button"
          className="link"
          aria-controls={textId}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? "Show less" : more}
        </button>
      ) : null}
    </section>
  );
}
