import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { fakeOverflow, LONG_STATEMENT } from "../test/layout";
import { StatementShown } from "./StatementShown";

/** jsdom has no `document.fonts`; give it one whose `ready` the test settles. */
function fakeFonts(): () => Promise<void> {
  let settle!: () => void;
  const ready = new Promise<void>((resolve) => (settle = resolve));
  Object.defineProperty(document, "fonts", { value: { ready }, configurable: true });
  return async () => {
    settle();
    await act(() => ready);
  };
}

afterEach(() => {
  delete (document as { fonts?: unknown }).fonts;
});

it("says whether the fold is open, on the button that opens it", async () => {
  fakeOverflow();
  const user = userEvent.setup();
  render(<StatementShown statement={LONG_STATEMENT} />);
  const shown = screen.getByRole("region", { name: "Value statement" });
  const fold = within(shown).getByRole("button", { name: "Show the whole statement" });
  expect(fold).toHaveAttribute("aria-expanded", "false");
  await user.click(fold);
  // the same button, so focus stays on it
  expect(fold).toHaveFocus();
  expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(fold).toHaveAccessibleName("Show less");
});

it("measures again once the font has loaded, since it can wrap the text onto more lines", async () => {
  const fontsLoaded = fakeFonts();
  render(<StatementShown statement={LONG_STATEMENT} />);
  expect(screen.queryByRole("button")).toBeNull();
  // the bundled font arrives and the statement now runs past three lines
  fakeOverflow();
  await fontsLoaded();
  expect(screen.getByRole("button", { name: "Show the whole statement" })).toBeInTheDocument();
});

it("does not measure a statement that has gone by the time the font loads", async () => {
  const fontsLoaded = fakeFonts();
  const { unmount } = render(<StatementShown statement={LONG_STATEMENT} />);
  const height = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get");
  unmount();
  await fontsLoaded();
  expect(height).not.toHaveBeenCalled();
});
