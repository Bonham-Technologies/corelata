import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { HelpDialog } from "./HelpDialog";

it("uses none of the engine's words (R-M18-14)", () => {
  render(<HelpDialog open onClose={() => {}} />);
  const banned =
    /\b(runs?|reruns?|discovery|gate|audit|conveyor|conveying|conveyed|ingesting|iterations?|verdicts?|evidence units?|findings?|digested|packs?)\b/i;
  expect(screen.getByRole("dialog", { name: "Help" }).textContent).not.toMatch(banned);
});

it("explains the keys, every status with its symbol, the steps and the standards results", async () => {
  const onClose = vi.fn();
  render(<HelpDialog open onClose={onClose} />);
  const help = screen.getByRole("dialog", { name: "Help" });
  expect(help).toHaveTextContent("Open this help");
  expect(help).toHaveTextContent("Move between the tabs of a review");
  expect(help).toHaveTextContent("Close a menu or a dialog");
  for (const status of [
    "… writing",
    "● waiting for review",
    "✓ accepted",
    "↺ returned",
    "⚠ not supported by the sources",
    "! couldn't finish",
    "■ stopped",
  ]) {
    expect(help).toHaveTextContent(status);
  }
  const steps = within(help).getAllByRole("list")[1]!;
  expect(within(steps).getAllByRole("listitem")).toHaveLength(8);
  expect(steps).toHaveTextContent("Checking the value statement");
  for (const result of [
    "✓ met",
    "✗ not met",
    "– doesn't apply",
    "◇ attested",
    "Return with note",
  ]) {
    expect(help).toHaveTextContent(result);
  }
  await userEvent.setup().click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
});

it("opens at the top: focus lands on its heading, not on Close at the bottom", async () => {
  function Host() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open help</button>
        <HelpDialog open={open} onClose={() => setOpen(false)} />
      </>
    );
  }
  const user = userEvent.setup();
  render(<Host />);
  await user.click(screen.getByRole("button", { name: "Open help" }));
  const heading = within(screen.getByRole("dialog", { name: "Help" })).getByRole("heading", {
    name: "Help",
    level: 2,
  });
  expect(heading).toHaveFocus();
  expect(heading).toHaveAttribute("tabindex", "-1");
  expect(screen.getByRole("button", { name: "Close" })).not.toHaveFocus();
});

it("words the failed status with the screen's name, Writing the report", () => {
  render(<HelpDialog open onClose={() => {}} />);
  const help = screen.getByRole("dialog", { name: "Help" });
  expect(help).toHaveTextContent(
    "Something went wrong; the “Writing the report” screen says what.",
  );
  expect(help).not.toHaveTextContent("progress page");
});
