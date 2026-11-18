import { vi } from "vitest";

/** A statement long enough to run past three lines at any width the pages are drawn at. */
export const LONG_STATEMENT =
  "Varna port capacity expansion matters to shippers who move grain across the Black Sea. "
    .repeat(6)
    .trim();

/** jsdom lays nothing out, so every element is 0 px tall. Make an element whose text is longer
 * than `chars` taller than its box, as a browser does when a three-line fold cuts it short. */
export function fakeOverflow(chars = 300): void {
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return (this.textContent ?? "").length > chars ? 120 : 0;
  });
}
