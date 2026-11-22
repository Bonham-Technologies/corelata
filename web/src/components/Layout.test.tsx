import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { makeQueryClient, Providers } from "../Providers";
import { routes } from "../routes";
import { info } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

it("shows the name, the theme toggle, Help and Settings, and no user or Sign out by default", async () => {
  renderApp("/new");
  const header = screen.getByRole("banner");
  expect(within(header).getByRole("link", { name: "Corelata" })).toHaveAttribute("href", "/new");
  expect(within(header).getByRole("button", { name: "Help" })).toBeInTheDocument();
  expect(within(header).getByRole("link", { name: "Settings" })).toHaveAttribute(
    "href",
    "/settings",
  );
  expect(within(header).getByRole("button", { name: /^Switch to the/ })).toBeInTheDocument();
  expect(await screen.findByText("Corelata 0.1.0")).toBeInTheDocument(); // the sidebar's foot
  expect(within(header).queryByRole("button", { name: "Sign out" })).toBeNull();
});

it("shows who is signed in and a Sign out form when the API reports them", async () => {
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({
        ...info,
        user: "ana",
        auth_mode: "trusted_header",
        logout_url: "/oauth2/sign_out",
      }),
    ),
  );
  renderApp("/new");
  expect(await screen.findByText("ana")).toBeInTheDocument();
  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(signOut.closest("form")).toHaveAttribute("action", "/oauth2/sign_out");
  expect(signOut.closest("form")).toHaveAttribute("method", "post");
  // signing out drops every project's draft (CRL-74) and nothing else
  sessionStorage.setItem("corelata.draft.p1", '{"statement":"x"}');
  sessionStorage.setItem("corelata.draft.p2", '{"statement":"y"}');
  sessionStorage.setItem("other", "kept");
  fireEvent.submit(signOut.closest("form")!);
  expect(sessionStorage.getItem("corelata.draft.p1")).toBeNull();
  expect(sessionStorage.getItem("corelata.draft.p2")).toBeNull();
  expect(sessionStorage.getItem("other")).toBe("kept");
});

it("opens Help with the ? key outside a text field, and from the header", async () => {
  const { user } = renderApp("/new");
  fireEvent.keyDown(window, { key: "?" });
  expect(await screen.findByRole("dialog", { name: "Help" })).toHaveAttribute("open");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Help" }));
  expect(screen.getByRole("dialog", { name: "Help" })).toHaveAttribute("open");
});

it("leaves the ? key to a text field", async () => {
  renderApp("/new");
  const field = document.createElement("textarea");
  document.body.appendChild(field);
  fireEvent.keyDown(field, { key: "?" });
  expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  field.remove();
});

it("opens the sidebar from the header on a narrow screen", async () => {
  const { user } = renderApp("/new");
  const toggle = screen.getByRole("button", { name: "Your projects" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("navigation", { name: "Your projects" }).closest(".sidebar")).toHaveClass(
    "open",
  );
  await user.click(screen.getByRole("link", { name: "+ New report" }));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

it("redirects the root to the new report screen and shows the not-found page elsewhere", async () => {
  const { router } = renderApp("/");
  expect(router.state.location.pathname).toBe("/new");
  renderApp("/nope");
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Start a new report" })).toHaveAttribute("href", "/new");
  await waitFor(() => expect(document.title).toBe("Page not found – Corelata"));
});

it("shows the info error inline when the API is unreachable", async () => {
  server.use(http.get("*/api/system/info", () => HttpResponse.error()));
  renderApp("/new");
  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("could not be reached");
});

it("replaces a crashing page inside the layout", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const Boom = () => {
    throw new Error("page exploded");
  };
  const root = routes[0] as { children: { children: RouteObject[] }[] } & RouteObject;
  const page = root.children[0]!;
  const withBoom = [
    {
      ...root,
      children: [{ ...page, children: [...page.children, { path: "boom", element: <Boom /> }] }],
    },
  ] as RouteObject[];
  const router = createMemoryRouter(withBoom, { initialEntries: ["/boom"] });
  render(
    <Providers client={makeQueryClient({ retry: false })}>
      <RouterProvider router={router} />
    </Providers>,
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Corelata" })).toBeInTheDocument();
});

it("switches the theme from the header and names the theme it switches to", async () => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  const { user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "Switch to the dark theme" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("corelata.theme")).toBe("dark");
  await user.click(screen.getByRole("button", { name: "Switch to the light theme" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  localStorage.clear();
});

it("moves focus to + New report when the narrow sidebar opens", async () => {
  const { user } = renderApp("/new");
  await user.click(screen.getByRole("button", { name: "Your projects" }));
  expect(screen.getByRole("link", { name: "+ New report" })).toHaveFocus();
});

it("closes the open sidebar with Esc and returns focus to its toggle", async () => {
  const { user } = renderApp("/new");
  const toggle = screen.getByRole("button", { name: "Your projects" });
  await user.click(toggle);
  await user.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.getByRole("navigation", { name: "Your projects" }).closest(".sidebar"),
  ).not.toHaveClass("open");
  expect(toggle).toHaveFocus();
  await user.keyboard("{Escape}"); // closed: nothing to do, and focus stays
  expect(toggle).toHaveFocus();
});

it("leaves Esc to an open dialog while the sidebar overlay is open: one Esc closes only Help", async () => {
  const { user } = renderApp("/new");
  const toggle = screen.getByRole("button", { name: "Your projects" });
  await user.click(toggle);
  fireEvent.keyDown(window, { key: "?" });
  const help = await screen.findByRole("dialog", { name: "Help" });
  await user.keyboard("{Escape}");
  // the browser answers Esc on a modal dialog with its cancel event, after the keydown
  fireEvent(help, new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  await user.keyboard("{Escape}"); // the next Esc is the overlay's
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

it("moves focus to the main area when a sidebar link closes the sidebar", async () => {
  const { user } = renderApp("/new");
  await user.click(screen.getByRole("button", { name: "Your projects" }));
  await user.click(screen.getByRole("link", { name: "+ New report" }));
  expect(screen.getByRole("main")).toHaveFocus();
  expect(screen.getByRole("main")).toHaveAttribute("tabindex", "-1");
});
