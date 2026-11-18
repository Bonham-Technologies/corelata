/** A promise the test settles itself. An msw handler awaits `promise`; the test checks the
 * loading state, then calls `resolve()` (R-M10-7: no real delays, no fake timers). */
export function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}
