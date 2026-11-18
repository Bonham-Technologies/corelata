import { COUNT_FROM } from "../lib/limits";

/** Whether a bounded field is near its limit, where its count shows (CRL-83). */
export function nearLimit(value: string, max: number): boolean {
  return value.length >= max * COUNT_FROM;
}

/** "3,700 of 4,000 characters" under a bounded textarea, shown only near the limit (CRL-83). The
 * textarea's maxLength stops the typing; this says why. While it shows, point the textarea's
 * aria-describedby at `id`, so a screen reader reads the count with the field. */
export function CharCount({ id, value, max }: { id: string; value: string; max: number }) {
  if (!nearLimit(value, max)) return null;
  return (
    <p id={id} className="muted">
      {value.length.toLocaleString()} of {max.toLocaleString()} characters
    </p>
  );
}
