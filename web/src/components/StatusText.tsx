import type { Status } from "../lib/status";

/** Copied from Coglossa (spec §2.2): a status in words, with its symbol, coloured by tone (never
 * colour alone). */
export function StatusText({ status, id }: { status: Status; id?: string }) {
  return (
    <span id={id} className={`status tone-${status.tone}`}>
      {status.symbol ? <span aria-hidden="true">{status.symbol} </span> : null}
      {status.text}
    </span>
  );
}
