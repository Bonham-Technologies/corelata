import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { info, noRuns, packs, project, source, sources } from "../../test/fixtures";
import { decodeSelection, SELECTION_PARAM } from "../../lib/selection";
import { nodeFormData, NodeFileClass } from "../../test/node-web";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

// The page mounts the run options, which read the packs.
beforeEach(() => server.use(http.get("*/api/packs", () => HttpResponse.json(packs))));

function serve(list = sources) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
}

it("lists the project's sources, all selected for the report by default, and toggles them", async () => {
  serve();
  const { user } = renderApp(`/new?project=${project.id}`);
  const region = await screen.findByRole("region", { name: "Sources" });
  const boxes = await within(region).findAllByRole("checkbox", { name: /Use .* in this report/ });
  expect(boxes).toHaveLength(2);
  expect(boxes.every((b) => (b as HTMLInputElement).checked)).toBe(true);
  expect(within(region).getByText("letter.coglossa.json")).toBeInTheDocument();
  expect(within(region).getByText("Coglossa run run-42")).toBeInTheDocument();
  await user.click(boxes[0]!);
  expect(boxes[0]).not.toBeChecked();
  expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
    "1 of 2 selected",
  );
  await user.click(boxes[0]!);
  expect(boxes[0]).toBeChecked();
});

it("uploads a file, adds and selects it (test_upload_adds_and_selects_the_source)", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  const list = [source];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      expect(form.get("kind")).toBe("file");
      const added = {
        ...source,
        id: "55555555-5555-5555-5555-555555555555",
        name: "more.md",
        format: "md",
      };
      list.push(added);
      return HttpResponse.json([added], { status: 201 });
    }),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  const input = await screen.findByLabelText("Choose files");
  await user.click(await screen.findByRole("checkbox", { name: "Use port.txt in this report" }));
  await user.upload(input, new File(["# Notes"], "more.md", { type: "text/markdown" }));
  await user.click(screen.getByRole("button", { name: "Upload" }));
  // the refreshed list can show the row a moment before the URL gains its id
  const added = await screen.findByRole("checkbox", { name: "Use more.md in this report" });
  await waitFor(() => expect(added).toBeChecked());
  // the uploaded file's chip is gone
  expect(
    within(screen.getByRole("list", { name: "Chosen files" })).queryByText("more.md"),
  ).toBeNull();
  expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).not.toBeChecked();
  expect((input as HTMLInputElement).value).toBe("");
  // the choice in the URL gained the new source (R-M17-6)
  const picked = new URLSearchParams(router.state.location.search).get(SELECTION_PARAM)!;
  expect([
    ...decodeSelection(
      picked,
      list.map((s) => s.id),
    ),
  ]).toEqual(["55555555-5555-5555-5555-555555555555"]);
});

it("an upload while every source is selected keeps every source selected, and the URL bare", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  const added = { ...source, id: "55555555-5555-5555-5555-555555555555", name: "more.md" };
  const list = [source];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.post(`*/api/projects/${project.id}/sources`, () => {
      list.push(added);
      return HttpResponse.json([added], { status: 201 });
    }),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  await user.upload(
    await screen.findByLabelText("Choose files"),
    new File(["# Notes"], "more.md", { type: "text/markdown" }),
  );
  await user.click(screen.getByRole("button", { name: "Upload" }));
  expect(
    await screen.findByRole("checkbox", { name: "Use more.md in this report", checked: true }),
  ).toBeChecked();
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked(),
  );
  expect(router.state.location.search).toBe(`?project=${project.id}`);
});

it("shows an upload rejection inline and keeps the form (test_upload_rejection_shows_detail)", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  serve([source]);
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, () =>
      HttpResponse.json(
        { detail: "big.pdf is larger than the 1 MB upload limit (api.max_upload_mb)" },
        { status: 413 },
      ),
    ),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const input = await screen.findByLabelText("Choose files");
  await user.upload(input, new File(["x"], "big.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("button", { name: "Upload" }));
  // the API's 413 names the limit, so its own line is shown on the file's chip
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "big.pdf: big.pdf is larger than the 1 MB upload limit",
  );
  expect(screen.getByRole("button", { name: "Try again: big.pdf" })).toBeEnabled();
  expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeInTheDocument();
  expect((input as HTMLInputElement).value).toBe("");
});

it("hides the Coglossa fetch when it is not configured", async () => {
  serve([source]);
  renderApp(`/new?project=${project.id}`);
  await screen.findByRole("region", { name: "Sources" });
  await screen.findByRole("checkbox", { name: "Use port.txt in this report" });
  expect(screen.queryByRole("textbox", { name: "Coglossa run id" })).not.toBeInTheDocument();
});

it("imports from Coglossa by run id and selects the imported source", async () => {
  const list = [source];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.get("*/api/system/info", () => HttpResponse.json({ ...info, coglossa: true })),
    http.post(`*/api/projects/${project.id}/sources/from-coglossa`, async ({ request }) => {
      expect(await request.json()).toEqual({ run_id: "run-42" });
      list.push(sources[1]!);
      return HttpResponse.json([sources[1]], { status: 201 });
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const field = await screen.findByRole("textbox", { name: "Coglossa run id" });
  await user.click(
    await screen.findByRole("checkbox", { name: `Use ${source.name} in this report` }),
  );
  await user.type(field, "run-42");
  await user.click(screen.getByRole("button", { name: "Fetch from Coglossa" }));
  await waitFor(() => expect(field).toHaveValue(""));
  // The refetched list can render the new source before its tick lands: the URL write goes
  // through React Router, whose state update is a transition and commits a render later. So
  // wait for the tick itself, not just for the checkbox (CRL-92).
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: `Use ${sources[1]!.name} in this report` }),
    ).toBeChecked(),
  );
  expect(
    screen.getByRole("checkbox", { name: `Use ${source.name} in this report` }),
  ).not.toBeChecked();
});

it("says when the Coglossa run is in the project already, and selects nothing new (CRL-126)", async () => {
  serve(sources);
  server.use(
    http.get("*/api/system/info", () => HttpResponse.json({ ...info, coglossa: true })),
    http.post(`*/api/projects/${project.id}/sources/from-coglossa`, () =>
      HttpResponse.json([{ ...sources[1]!, already_in_project: true }]),
    ),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const field = await screen.findByRole("textbox", { name: "Coglossa run id" });
  await user.click(
    await screen.findByRole("checkbox", { name: `Use ${sources[1]!.name} in this report` }),
  );
  await user.type(field, "run-42");
  await user.click(screen.getByRole("button", { name: "Fetch from Coglossa" }));
  const form = within(screen.getByRole("form", { name: "Import from Coglossa" }));
  expect(await form.findByRole("status")).toHaveTextContent(
    `Coglossa run run-42 is already in this project as ${sources[1]!.name}.`,
  );
  expect(field).toHaveValue("");
  expect(
    screen.getByRole("checkbox", { name: `Use ${sources[1]!.name} in this report` }),
  ).not.toBeChecked();
  await user.type(field, "run-43"); // the note is for the run fetched, not the next one
  expect(form.queryByRole("status")).toBeNull();
});

it("shows a Coglossa fetch failure inline and keeps the run id", async () => {
  serve([source]);
  server.use(
    http.get("*/api/system/info", () => HttpResponse.json({ ...info, coglossa: true })),
    http.post(`*/api/projects/${project.id}/sources/from-coglossa`, () =>
      HttpResponse.json({ detail: "Coglossa run run-9 not found" }, { status: 404 }),
    ),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const field = await screen.findByRole("textbox", { name: "Coglossa run id" });
  await user.type(field, "run-9");
  await user.click(screen.getByRole("button", { name: "Fetch from Coglossa" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not found");
  expect(field).toHaveValue("run-9");
});

it("says when a project has no sources yet", async () => {
  serve([]);
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByText("No sources yet. Add a file to begin.")).toBeInTheDocument();
});

it("shows a source-list failure inline", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () =>
      HttpResponse.json({ detail: "no such project" }, { status: 404 }),
    ),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("no such project");
});

it("moves focus to the selected-sources status after an upload (M18 polish F1)", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  const list = [source];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      expect(form.get("kind")).toBe("file");
      const added = {
        ...source,
        id: "55555555-5555-5555-5555-555555555555",
        name: "more.md",
        format: "md",
      };
      list.push(added);
      return HttpResponse.json([added], { status: 201 });
    }),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  const input = await screen.findByLabelText("Choose files");
  await user.click(await screen.findByRole("checkbox", { name: "Use port.txt in this report" }));
  await user.upload(input, new File(["# Notes"], "more.md", { type: "text/markdown" }));
  await user.click(screen.getByRole("button", { name: "Upload" }));
  // the refreshed list can show the row a moment before the URL gains its id
  await screen.findByRole("checkbox", { name: "Use more.md in this report" });
  const status = screen.getByRole("status", { name: "Selected sources" });
  await waitFor(() => expect(status).toHaveFocus());
  expect(status).toHaveAttribute("tabindex", "-1");
  expect(router.state.location.pathname).toBe("/new");
});

it("moves focus to the status once the first source arrives (M18 polish F1)", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  const list: (typeof source)[] = [];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      expect(form.get("kind")).toBe("file");
      const added = {
        ...source,
        id: "55555555-5555-5555-5555-555555555555",
        name: "more.md",
        format: "md",
      };
      list.push(added);
      return HttpResponse.json([added], { status: 201 });
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const input = await screen.findByLabelText("Choose files");
  await screen.findByText("No sources yet. Add a file to begin.");
  await user.upload(input, new File(["# Notes"], "more.md", { type: "text/markdown" }));
  await user.click(screen.getByRole("button", { name: "Upload" }));
  // the refreshed list can show the row a moment before the URL gains its id
  await screen.findByRole("checkbox", { name: "Use more.md in this report" });
  const status = screen.getByRole("status", { name: "Selected sources" });
  await waitFor(() => expect(status).toHaveFocus());
  expect(status).toHaveAttribute("tabindex", "-1");
});
