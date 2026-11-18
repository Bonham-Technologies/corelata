import { render, screen } from "@testing-library/react";
import { UsageSummary } from "./UsageSummary";

it("uses the singular for one call and renders nothing without usage", () => {
  const { rerender } = render(
    <UsageSummary usage={{ calls: 1, tokens_in: 10, tokens_out: 2, by_role: {} }} />,
  );
  expect(screen.getByRole("status", { name: "Token usage" })).toHaveTextContent(
    "1 model call · 10 in",
  );
  rerender(<UsageSummary usage={null} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
