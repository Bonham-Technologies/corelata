import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Tabs } from "./Tabs";

const TABS = [
  { id: "a", label: "Alpha" },
  { id: "b", label: "Beta" },
  { id: "c", label: "Gamma" },
];

function Host() {
  const [active, setActive] = useState("a");
  return (
    <Tabs label="Details" tabs={TABS} active={active} onChange={setActive}>
      {(id) => <p>Panel {id}</p>}
    </Tabs>
  );
}

it("is a tablist with arrow-key navigation and one visible panel", async () => {
  const user = userEvent.setup();
  render(<Host />);
  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(3);
  expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel a");
  await user.click(tabs[1]!);
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel b");
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel c");
  expect(tabs[2]).toHaveFocus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel a");
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel c");
  await user.keyboard("{Home}");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel a");
  await user.keyboard("{End}");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel c");
});

it("ignores other keys and falls back to the first tab for an unknown active id", async () => {
  const user = userEvent.setup();
  render(
    <Tabs label="Details" tabs={TABS} active="zzz" onChange={() => {}}>
      {(id) => <p>Panel {id}</p>}
    </Tabs>,
  );
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel a");
  screen.getAllByRole("tab")[0]!.focus();
  await user.keyboard("x");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel a");
});

it("links the selected tab and its panel, and only those", () => {
  render(<Host />);
  const [selected, ...others] = screen.getAllByRole("tab");
  const panel = screen.getByRole("tabpanel");
  expect(selected!.getAttribute("aria-controls")).toBe(panel.id);
  expect(panel.getAttribute("aria-labelledby")).toBe(selected!.id);
  expect(document.getElementById(panel.id)).toBe(panel);
  for (const tab of others) expect(tab).not.toHaveAttribute("aria-controls");
});
