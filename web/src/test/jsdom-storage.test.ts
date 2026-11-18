import { pointStorageAtJsdom } from "./jsdom-storage";

it("points the storages at jsdom's", () => {
  const stored = new Map<string, string>();
  const area = { setItem: (k: string, v: string) => stored.set(k, v) };
  const target: Record<string, unknown> = { jsdom: { window: { localStorage: area } } };
  pointStorageAtJsdom(target);
  expect(target.localStorage).toBe(area);
});

it("says so, rather than silently keeping Node's storage, when global.jsdom is missing", () => {
  expect(() => pointStorageAtJsdom({})).toThrow(/global\.jsdom/);
});
