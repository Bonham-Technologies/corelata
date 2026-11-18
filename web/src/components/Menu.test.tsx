import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "./Dialog";
import { Menu } from "./Menu";

function Example({ onPick }: { onPick: () => void }) {
  return (
    <>
      <p>Outside</p>
      <Menu label="Download" button="Download ▾">
        {(close) => (
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              onPick();
              close();
            }}
          >
            Word document
          </button>
        )}
      </Menu>
    </>
  );
}

it("opens, picks, and closes by Esc or a click outside", async () => {
  const user = userEvent.setup();
  const onPick = vi.fn();
  render(<Example onPick={onPick} />);
  const button = screen.getByRole("button", { name: "Download" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  await user.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  await user.click(screen.getByRole("menuitem", { name: "Word document" }));
  expect(onPick).toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(button);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(button);
  await user.click(screen.getByText("Outside"));
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

function Several() {
  return (
    <Menu label="Actions" button="⋯">
      {(close) => (
        <>
          <button role="menuitem" type="button" onClick={close}>
            One
          </button>
          <button role="menuitem" type="button" aria-disabled="true">
            Two (inert but focusable)
          </button>
          <button role="menuitem" type="button" disabled>
            Skipped
          </button>
          <a role="menuitem" href="/three" onClick={close}>
            Three
          </a>
        </>
      )}
    </Menu>
  );
}

it("focuses the first item on opening and walks the items with the arrow keys", async () => {
  const user = userEvent.setup();
  render(<Several />);
  await user.click(screen.getByRole("button", { name: "Actions" }));
  expect(screen.getByRole("menuitem", { name: "One" })).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: /Two/ })).toHaveFocus(); // aria-disabled still lands
  await user.keyboard("{ArrowDown}"); // the natively disabled one is skipped
  expect(screen.getByRole("menuitem", { name: "Three" })).toHaveFocus();
  await user.keyboard("{ArrowDown}"); // wraps
  expect(screen.getByRole("menuitem", { name: "One" })).toHaveFocus();
  await user.keyboard("{ArrowUp}"); // wraps back
  expect(screen.getByRole("menuitem", { name: "Three" })).toHaveFocus();
  await user.keyboard("{Home}");
  expect(screen.getByRole("menuitem", { name: "One" })).toHaveFocus();
  await user.keyboard("{End}");
  expect(screen.getByRole("menuitem", { name: "Three" })).toHaveFocus();
});

it("returns focus to the menu button on Escape, on choosing an item, and on a click outside", async () => {
  const user = userEvent.setup();
  render(<Example onPick={() => {}} />);
  const button = screen.getByRole("button", { name: "Download" });
  await user.click(button);
  await user.keyboard("{Escape}");
  expect(button).toHaveFocus();
  await user.click(button);
  await user.click(screen.getByRole("menuitem", { name: "Word document" }));
  expect(button).toHaveFocus();
  await user.click(button);
  await user.click(screen.getByText("Outside"));
  await vi.waitFor(() => expect(button).toHaveFocus());
});

it("lets Escape close only the menu, not the dialog around it", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  const outer = vi.fn();
  render(
    <div onKeyDown={outer}>
      <Dialog open label="Settings" onClose={onClose}>
        <Several />
      </Dialog>
    </div>,
  );
  await user.click(screen.getByRole("button", { name: "Actions" }));
  const item = screen.getByRole("menuitem", { name: "One" });
  expect(fireEvent.keyDown(item, { key: "Escape" })).toBe(false); // default prevented
  expect(outer).not.toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});

it("ArrowUp from the button goes to the last item", async () => {
  const user = userEvent.setup();
  render(<Several />);
  const button = screen.getByRole("button", { name: "Actions" });
  await user.click(button);
  button.focus();
  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("menuitem", { name: "Three" })).toHaveFocus();
});

it("closes when focus tabs out of it", async () => {
  const user = userEvent.setup();
  render(
    <>
      <Several />
      <button type="button">After</button>
    </>,
  );
  await user.click(screen.getByRole("button", { name: "Actions" }));
  await user.keyboard("{Tab}{Tab}"); // Two, then Three (Skipped is disabled)
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await user.keyboard("{Tab}");
  expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("closes on Escape even when focus is not inside it", async () => {
  const user = userEvent.setup();
  render(<Several />);
  await user.click(screen.getByRole("button", { name: "Actions" }));
  (document.activeElement as HTMLElement).blur();
  expect(screen.getByRole("menu")).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});
