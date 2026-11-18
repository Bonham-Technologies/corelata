import source from "../../public/theme-init.js?raw";

function run(stored: string | null | "throw", prefersDark: boolean | null): string | undefined {
  vi.stubGlobal("localStorage", {
    getItem: () => {
      if (stored === "throw") throw new Error("blocked");
      return stored;
    },
  });
  vi.stubGlobal(
    "matchMedia",
    prefersDark === null
      ? undefined
      : (q: string) => ({ matches: prefersDark && q.includes("dark") }),
  );
  delete document.documentElement.dataset.theme;
  new Function(source)();
  return document.documentElement.dataset.theme;
}

it.each([
  ["dark", false, "dark"],
  ["light", true, "light"],
  ["system", true, "dark"],
  [null, false, "light"],
  ["throw", true, "dark"],
  [null, null, "light"],
] as const)("stored %s, computer dark %s: %s", (stored, dark, expected) => {
  expect(run(stored, dark)).toBe(expected);
});
