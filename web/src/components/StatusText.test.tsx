import { render, screen } from "@testing-library/react";
import { StatusText } from "./StatusText";

it("shows a status's symbol before its words, and the words alone without one", () => {
  const { container, rerender } = render(
    <StatusText status={{ text: "Ready", tone: "ok", symbol: "✓" }} />,
  );
  expect(container.querySelector("[aria-hidden='true']")).toHaveTextContent("✓");
  expect(screen.getByText("Ready")).toHaveClass("status", "tone-ok");
  rerender(<StatusText status={{ text: "Waiting", tone: "none", symbol: "" }} />);
  expect(container.querySelector("[aria-hidden='true']")).toBeNull();
  expect(screen.getByText("Waiting")).toHaveClass("tone-none");
});
