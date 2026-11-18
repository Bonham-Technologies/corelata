import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { makeQueryClient, Providers } from "../Providers";
import { routes } from "../routes";

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  render(
    <Providers client={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { router, user, queryClient };
}

/** One component as the page at `path` (which sets its search parameters), with a query
 * client: for components that keep state in the URL. */
export function renderRoute(element: ReactNode, path: string) {
  const pathname = new URL(path, "http://corelata.test").pathname;
  const router = createMemoryRouter([{ path: pathname, element }], { initialEntries: [path] });
  const queryClient = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  render(
    <Providers client={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { router, user, queryClient };
}

/** A component outside the router, with a query client. `unmount` is leaving the page. */
export function renderWithClient(ui: ReactNode) {
  const queryClient = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  const { unmount } = render(<Providers client={queryClient}>{ui}</Providers>);
  return { user, queryClient, unmount };
}
