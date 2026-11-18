import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ApiError } from "../api/client";
import { renderApp } from "../test/render";
import { ErrorMessage, messageOf } from "./ErrorMessage";
import { Loading } from "./Loading";
import { RouteError } from "./RouteError";

it("links the not-found page back to the new report screen", async () => {
  renderApp("/nope");
  expect(await screen.findByRole("link", { name: "Start a new report" })).toHaveAttribute(
    "href",
    "/new",
  );
});

it("shows a message for an API error, an Error, and anything else", () => {
  expect(messageOf(new ApiError(404, "gone"))).toBe("gone");
  expect(messageOf(new Error("boom"))).toBe("boom");
  expect(messageOf("odd")).toBe("Something went wrong.");
  render(<ErrorMessage error={new ApiError(409, "already cancelled")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("already cancelled");
});

it("announces loading with a polite status", () => {
  render(<Loading />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  render(<Loading what="Loading runs" />);
  expect(screen.getByText("Loading runs…")).toBeInTheDocument();
});

it("replaces a page that throws, with a way back", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const Boom = () => {
    throw new Error("render failed");
  };
  const router = createMemoryRouter(
    [{ path: "/", element: <Boom />, errorElement: <RouteError /> }],
    { initialEntries: ["/"] },
  );
  render(<RouterProvider router={router} />);
  expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("render failed");
  expect(screen.getByRole("link", { name: "Back to the start" })).toHaveAttribute("href", "/new");
});
