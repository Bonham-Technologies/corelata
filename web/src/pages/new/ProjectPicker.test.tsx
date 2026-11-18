import { act, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { noRuns, packs, project, source } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

// The page mounts the run options, which read the packs.
beforeEach(() => server.use(http.get("*/api/packs", () => HttpResponse.json(packs))));

const other = { ...project, id: "99999999-9999-9999-9999-999999999999", name: "Baltic" };

it("lists projects, selects one into the URL and creates a new one", async () => {
  let created = 0;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json(created ? [project, other] : [project])),
    http.post("*/api/projects", async ({ request }) => {
      created += 1;
      expect(await request.json()).toEqual({ name: "Baltic" });
      return HttpResponse.json(other, { status: 201 });
    }),
    http.get("*/api/projects/*/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  const { router, user } = renderApp("/new");
  const picker = await screen.findByRole("combobox", { name: "Project" });
  expect(picker).toHaveValue("");
  await user.selectOptions(picker, project.id);
  expect(router.state.location.search).toBe(`?project=${project.id}`);
  expect(await screen.findByRole("heading", { name: project.name })).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "+ New report" }));
  await user.click(await screen.findByRole("button", { name: "New project" }));
  await user.type(screen.getByRole("textbox", { name: "Project name" }), "Baltic");
  await user.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(router.state.location.search).toBe(`?project=${other.id}`));
  expect(await screen.findByRole("heading", { name: "Baltic" })).toBeInTheDocument();
});

it("shows a duplicate-name conflict inline", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.post("*/api/projects", () =>
      HttpResponse.json({ detail: "a project named 'Black Sea' already exists" }, { status: 409 }),
    ),
  );
  const { user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "New project" }));
  await user.type(screen.getByRole("textbox", { name: "Project name" }), "Black Sea");
  await user.click(screen.getByRole("button", { name: "Create" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
});

it("keeps the project from the URL on reload", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("heading", { name: project.name })).toBeInTheDocument();
  expect(await screen.findByRole("region", { name: "Sources" })).toBeInTheDocument();
});

it("cancels the new-project form and leaves the URL without a project", async () => {
  server.use(http.get("*/api/projects", () => HttpResponse.json([project])));
  const { router, user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "New project" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("textbox", { name: "Project name" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), "");
  expect(router.state.location.search).toBe("");
});

it("shows a project-list failure inline", async () => {
  server.use(
    http.get("*/api/projects", () =>
      HttpResponse.json({ detail: "database offline" }, { status: 400 }),
    ),
  );
  renderApp("/new");
  // the sidebar shows it too (M18 spec §3.3)
  expect(await within(screen.getByRole("main")).findByRole("alert")).toHaveTextContent(
    "database offline",
  );
});

it("shows no project field while the list is loading", async () => {
  server.use(
    http.get("*/api/projects", async () => {
      await delay(50);
      return HttpResponse.json([project]);
    }),
  );
  renderApp("/new");
  expect(await screen.findByText("Loading projects…")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(await screen.findByRole("combobox", { name: "Project" })).toBeInTheDocument();
});

it("does not keep a stale create error after cancelling", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.post("*/api/projects", () =>
      HttpResponse.json({ detail: "a project named 'X' already exists" }, { status: 409 }),
    ),
  );
  const { user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "New project" }));
  await user.type(screen.getByRole("textbox", { name: "Project name" }), "X");
  await user.click(screen.getByRole("button", { name: "Create" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("does not carry a source selection across browser navigation to another project", async () => {
  const other = { ...project, id: "99999999-9999-9999-9999-999999999999", name: "Baltic" };
  const sourcesB = [{ ...source, id: "88888888-8888-8888-8888-888888888888", name: "b.txt" }];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project, other])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([source])),
    http.get(`*/api/projects/${other.id}/sources`, () => HttpResponse.json(sourcesB)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  const box = await screen.findByRole("checkbox", { name: "Use port.txt in this report" });
  await user.click(box);
  expect(box).not.toBeChecked();
  await act(() => router.navigate(`/new?project=${other.id}`));
  expect(
    await screen.findByRole("checkbox", { name: "Use b.txt in this report", checked: true }),
  ).toBeChecked();
});

it("moves focus to the new project's heading after Create (M18 polish F1)", async () => {
  let created = false;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json(created ? [project, other] : [project])),
    http.post("*/api/projects", () => {
      created = true;
      return HttpResponse.json(other, { status: 201 });
    }),
    http.get("*/api/projects/*/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  const { user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "New project" }));
  await user.type(screen.getByRole("textbox", { name: "Project name" }), "Baltic");
  await user.click(screen.getByRole("button", { name: "Create" }));
  const heading = await screen.findByRole("heading", { name: "Baltic" });
  await waitFor(() => expect(heading).toHaveFocus());
  expect(heading).toHaveAttribute("tabindex", "-1");
});

it("leaves focus alone when a project is chosen from the list", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get("*/api/projects/*/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  const { user } = renderApp("/new");
  await user.selectOptions(await screen.findByRole("combobox", { name: "Project" }), project.id);
  const heading = await screen.findByRole("heading", { name: project.name });
  expect(heading).not.toHaveFocus();
});
