import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ConfirmDialog } from "./ConfirmDialog";

function Host({ onConfirm }: { onConfirm: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      <ConfirmDialog
        open={open}
        title="Cancel this run?"
        confirmLabel="Cancel run"
        danger
        onConfirm={() => {
          onConfirm();
          setOpen(false);
        }}
        onCancel={() => setOpen(false)}
      >
        <p>The report will not be produced.</p>
      </ConfirmDialog>
    </>
  );
}

it("opens as a modal dialog, confirms, and returns focus to the opener on cancel", async () => {
  const confirm = vi.fn();
  const user = userEvent.setup();
  render(<Host onConfirm={confirm} />);
  const opener = screen.getByRole("button", { name: "Open" });
  await user.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "Cancel this run?" });
  expect(dialog).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Keep going" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  await user.click(opener);
  await user.click(screen.getByRole("button", { name: "Cancel run" }));
  expect(confirm).toHaveBeenCalledTimes(1);
});

it("closes through the dialog's own cancel event and disables both buttons while busy", async () => {
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Sure?"
      confirmLabel="Do it"
      busy
      onConfirm={() => {}}
      onCancel={onCancel}
    >
      <p>Body</p>
    </ConfirmDialog>,
  );
  const dialog = await screen.findByRole("dialog", { name: "Sure?" });
  expect(screen.getByRole("button", { name: "Do it" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Keep going" })).toBeDisabled();
  const escape = new Event("cancel", { cancelable: true });
  fireEvent(dialog, escape);
  expect(escape.defaultPrevented).toBe(true); // Escape keeps the dialog open while busy
  expect(onCancel).not.toHaveBeenCalled();
  expect(dialog).toBeVisible();
});

it("closes through the dialog's own cancel event when idle", async () => {
  const onCancel = vi.fn();
  render(
    <ConfirmDialog open title="Sure?" confirmLabel="Do it" onConfirm={() => {}} onCancel={onCancel}>
      <p>Body</p>
    </ConfirmDialog>,
  );
  fireEvent(await screen.findByRole("dialog", { name: "Sure?" }), new Event("cancel"));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

it("keeps the confirm button disabled while confirmDisabled is set", async () => {
  render(
    <ConfirmDialog
      open
      title="Note"
      confirmLabel="Send"
      confirmDisabled
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );
  await screen.findByRole("dialog", { name: "Note" });
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Keep going" })).toBeEnabled();
});

it("carries the shared dialog class and a neutral cancel button", async () => {
  render(
    <ConfirmDialog
      open
      title="Stop this report?"
      confirmLabel="Stop"
      danger
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );
  const dialog = await screen.findByRole("dialog", { name: "Stop this report?" });
  expect(dialog).toHaveClass("dialog");
  const cancel = screen.getByRole("button", { name: "Keep going" });
  expect(cancel).not.toHaveClass("secondary");
  expect(cancel).not.toHaveClass("primary");
  expect(screen.getByRole("button", { name: "Stop" })).toHaveClass("danger");
});

it("gives a non-danger confirm button the primary class", async () => {
  render(
    <ConfirmDialog
      open
      title="Return it?"
      confirmLabel="Return"
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );
  await screen.findByRole("dialog", { name: "Return it?" });
  const confirm = screen.getByRole("button", { name: "Return" });
  expect(confirm).toHaveClass("primary");
  expect(confirm).not.toHaveClass("danger");
});

it("names the pending action on the confirm button while busy (CRL-43)", async () => {
  const { rerender } = render(
    <ConfirmDialog
      open
      title="Return it?"
      confirmLabel="Return"
      busyLabel="Returning…"
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );
  await screen.findByRole("dialog", { name: "Return it?" });
  expect(screen.getByRole("button", { name: "Return" })).toBeEnabled();
  rerender(
    <ConfirmDialog
      open
      busy
      title="Return it?"
      confirmLabel="Return"
      busyLabel="Returning…"
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  );
  expect(screen.getByRole("button", { name: "Returning…" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Return" })).not.toBeInTheDocument();
});
