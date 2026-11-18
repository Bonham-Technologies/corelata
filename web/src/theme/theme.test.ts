import { act, renderHook } from "@testing-library/react";
import {
  applyTheme,
  resetThemeForTests,
  resolveTheme,
  setThemeChoice,
  storedChoice,
  THEME_KEY,
  useTheme,
} from "./theme";

function media(dark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: dark,
    addEventListener: (_: string, l: () => void) => listeners.add(l),
    removeEventListener: (_: string, l: () => void) => listeners.delete(l),
  };
  vi.stubGlobal("matchMedia", () => query);
  return {
    flip(next: boolean) {
      query.matches = next;
      listeners.forEach((l) => l());
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  resetThemeForTests();
  delete document.documentElement.dataset.theme;
});

it("follows the computer until a choice is stored", () => {
  media(true);
  expect(storedChoice()).toBe("system");
  applyTheme();
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(resolveTheme("light", true)).toBe("light");
  expect(resolveTheme("system", false)).toBe("light");
});

it("stores a choice and applies it", () => {
  media(false);
  setThemeChoice("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  localStorage.setItem(THEME_KEY, "purple");
  expect(storedChoice()).toBe("system"); // an unknown value is ignored
});

it("falls back to memory when storage throws", () => {
  media(false);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  setThemeChoice("dark");
  expect(storedChoice()).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it("updates live when the computer's setting changes", () => {
  const m = media(false);
  const { result } = renderHook(() => useTheme());
  expect(result.current).toMatchObject({ choice: "system", theme: "light" });
  act(() => m.flip(true));
  expect(result.current.theme).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  act(() => result.current.setChoice("light"));
  expect(result.current).toMatchObject({ choice: "light", theme: "light" });
});

it("works without matchMedia", () => {
  vi.stubGlobal("matchMedia", undefined);
  expect(resolveTheme("system")).toBe("light");
});

it("subscribes to the store and the colour scheme once per hook", () => {
  const addEventListener = vi.fn();
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener,
    removeEventListener() {},
  }));
  const { unmount } = renderHook(() => useTheme());
  expect(addEventListener).toHaveBeenCalledTimes(1);
  unmount();
});

it("follows a stored choice and the computer's setting through one snapshot", () => {
  const scheme = media(true);
  const { result } = renderHook(() => useTheme());
  expect(result.current).toMatchObject({ choice: "system", theme: "dark" });
  act(() => scheme.flip(false));
  expect(result.current).toMatchObject({ choice: "system", theme: "light" });
  act(() => setThemeChoice("dark"));
  expect(result.current).toMatchObject({ choice: "dark", theme: "dark" });
});
