/** Newer Node versions define their own localStorage global (empty without a flag), which
 * hides jsdom's. Point both storages at jsdom's so tests see a working Storage everywhere.
 * Vitest hands the jsdom instance over as `global.jsdom`; if a Vitest upgrade moves it, fail
 * loudly rather than leave tests running on Node's broken storage. */
export function pointStorageAtJsdom(global: object): void {
  const dom = (global as { jsdom?: { window: Window } }).jsdom;
  if (!dom) {
    throw new Error(
      "jsdom-env: Vitest no longer exposes the jsdom instance as global.jsdom, so localStorage " +
        "cannot be pointed at jsdom's. Update src/test/jsdom-storage.ts for the new Vitest.",
    );
  }
  for (const key of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(global, key, { configurable: true, get: () => dom.window[key] });
  }
}
