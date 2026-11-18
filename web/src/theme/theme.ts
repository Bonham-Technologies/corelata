import { useSyncExternalStore } from "react";

/** Copied from Coglossa (spec §2.2): the reader's theme. "system" follows the computer's
 * setting, live. */
export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_KEY = "corelata.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

// When the browser refuses storage (a private window, a policy), the choice lasts the session.
let memory: ThemeChoice | null = null;
const listeners = new Set<() => void>();

function isChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

function media(): MediaQueryList | undefined {
  return typeof globalThis.matchMedia === "function"
    ? globalThis.matchMedia(DARK_QUERY)
    : undefined;
}

export function storedChoice(): ThemeChoice {
  if (memory !== null) return memory;
  try {
    const value = localStorage.getItem(THEME_KEY);
    return isChoice(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(choice: ThemeChoice, prefersDark = media()?.matches ?? false): Theme {
  if (choice === "system") return prefersDark ? "dark" : "light";
  return choice;
}

export function applyTheme(choice: ThemeChoice = storedChoice()): void {
  document.documentElement.dataset.theme = resolveTheme(choice);
}

export function setThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice);
    memory = null;
  } catch {
    memory = choice;
  }
  applyTheme(choice);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const query = media();
  const onChange = () => {
    if (storedChoice() === "system") applyTheme("system");
    listener();
  };
  query?.addEventListener("change", onChange);
  return () => {
    listeners.delete(listener);
    query?.removeEventListener("change", onChange);
  };
}

export function useTheme(): {
  choice: ThemeChoice;
  theme: Theme;
  setChoice: (choice: ThemeChoice) => void;
} {
  // One subscription: the snapshot is a string, so React compares it by value.
  const snapshot = useSyncExternalStore(subscribe, () => {
    const choice = storedChoice();
    return `${choice} ${resolveTheme(choice)}`;
  });
  const [choice, theme] = snapshot.split(" ") as [ThemeChoice, Theme];
  return { choice, theme, setChoice: setThemeChoice };
}

export function resetThemeForTests(): void {
  memory = null;
}
