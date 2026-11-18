import { fireEvent, render, screen } from "@testing-library/react";
import { Dialog } from "./Dialog";

it("shows its children only while open, and Esc asks the parent instead of closing", () => {
  const onClose = vi.fn();
  const { rerender } = render(
    <Dialog open label="Help" onClose={onClose}>
      <p>Inside</p>
    </Dialog>,
  );
  const dialog = screen.getByRole("dialog", { name: "Help" });
  expect(dialog).toHaveAttribute("open");
  expect(dialog).toHaveClass("dialog");
  const escape = new Event("cancel", { cancelable: true });
  fireEvent(dialog, escape);
  expect(escape.defaultPrevented).toBe(true); // the parent decides
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(dialog).toHaveAttribute("open");
  rerender(
    <Dialog open={false} label="Help" onClose={onClose} className="dialog help">
      <p>Inside</p>
    </Dialog>,
  );
  expect(dialog).not.toHaveAttribute("open");
  expect(dialog).toHaveClass("dialog", "help");
  expect(screen.queryByText("Inside")).toBeNull();
});
