import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { ApiError, errorText } from "../../api/client";
import { project, source } from "../../test/fixtures";
import { nodeFormData, NodeFileClass } from "../../test/node-web";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { AddSources, fileProblem, sizeText, uploadErrorText } from "./AddSources";

const MB = 1024 * 1024;
const file = (name: string, bytes = 10) => new File(["x".repeat(bytes)], name);

beforeEach(async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
});

function serveUploads(fail: Record<string, Response> = {}) {
  const order: { name: string; kind: string }[] = [];
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      const name = (form.get("file") as File).name;
      order.push({ name, kind: String(form.get("kind")) });
      if (fail[name]) return fail[name]!.clone();
      return HttpResponse.json([{ ...source, id: `id-${name}`, name }], { status: 201 });
    }),
  );
  return order;
}

const chips = () => within(screen.getByRole("list", { name: "Chosen files" }));

it("takes several files by drop, uploads them in order, one request each, and hands each one on", async () => {
  const order = serveUploads();
  const added = vi.fn();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={added} />,
  );
  fireEvent.drop(screen.getByText("Drop files here, or click to choose").closest("label")!, {
    dataTransfer: { files: [file("a.txt"), file("b.pdf", 2 * MB)] },
  });
  expect(
    chips()
      .getAllByRole("listitem")
      .map((li) => li.textContent),
  ).toEqual(["a.txt 1 KB×", "b.pdf 2 MB×"]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(2));
  expect(order).toEqual([
    { name: "a.txt", kind: "file" },
    { name: "b.pdf", kind: "file" },
  ]);
  expect(added.mock.calls.map(([list]) => list[0].name)).toEqual(["a.txt", "b.pdf"]);
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});

it("marks a file over the limit and one of another type at once, and sends neither", async () => {
  const order = serveUploads();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />,
  );
  // dropped, so the file input's accept list does not filter them first
  fireEvent.drop(screen.getByText("Drop files here, or click to choose").closest("label")!, {
    dataTransfer: { files: [file("notes.pdf", 6 * MB), file("photo.png"), file("ok.md")] },
  });
  const alerts = chips().getAllByRole("alert");
  expect(alerts[0]).toHaveTextContent("notes.pdf is 6 MB, and the limit is 4 MB.");
  expect(alerts[1]).toHaveTextContent("photo.png isn't a file type Corelata reads");
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(order.map((o) => o.name)).toEqual(["ok.md"]));
  expect(chips().getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled(); // nothing left to send
  await user.click(screen.getByRole("button", { name: "Remove notes.pdf" }));
  expect(chips().getAllByRole("listitem")).toHaveLength(1);
});

it("takes .markdown and .xhtml files, which the engine reads, in the picker and by drop", async () => {
  const order = serveUploads();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />,
  );
  const input = screen.getByLabelText("Choose files");
  expect(input.getAttribute("accept")!.split(",")).toEqual(
    expect.arrayContaining([".markdown", ".xhtml"]),
  );
  fireEvent.drop(screen.getByText("Drop files here, or click to choose").closest("label")!, {
    dataTransfer: { files: [file("notes.markdown"), file("page.xhtml")] },
  });
  expect(chips().queryAllByRole("alert")).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(order.map((o) => o.name)).toEqual(["notes.markdown", "page.xhtml"]));
});

it("keeps a failed file's chip with the reason and Try again while the next one carries on", async () => {
  const order = serveUploads({
    "a.txt": new Response("<html>413</html>", { status: 413 }),
  });
  const added = vi.fn();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={added} />,
  );
  await user.selectOptions(screen.getByRole("combobox", { name: "Add as" }), "coglossa_export");
  await user.upload(screen.getByLabelText("Choose files"), [file("a.txt"), file("b.json")]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(1));
  expect(order).toEqual([
    { name: "a.txt", kind: "coglossa_export" },
    { name: "b.json", kind: "coglossa_export" },
  ]);
  expect(chips().getByRole("alert")).toHaveTextContent("a.txt: too large for this server");
  serveUploads(); // the proxy's limit was raised
  await user.click(chips().getByRole("button", { name: "Try again: a.txt" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(2));
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});

it("names the file on each failed chip's Try again, and marks a chip busy while it uploads", async () => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const name = ((await request.formData()).get("file") as File).name;
      if (name === "c.txt") {
        await held;
        return HttpResponse.json([{ ...source, id: "id-c", name }], { status: 201 });
      }
      return HttpResponse.json({ detail: `${name} is empty` }, { status: 422 });
    }),
  );
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />,
  );
  await user.upload(screen.getByLabelText("Choose files"), [
    file("a.pdf"),
    file("b.pdf"),
    file("c.txt"),
  ]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  const uploading = await waitFor(() => {
    const busy = chips()
      .getAllByRole("listitem")
      .filter((li) => li.getAttribute("aria-busy") === "true");
    expect(busy).toHaveLength(1);
    return busy[0]!;
  });
  expect(uploading).toHaveTextContent("c.txt");
  expect(chips().getByRole("button", { name: /Try again: a\.pdf/ })).toBeInTheDocument();
  expect(chips().getByRole("button", { name: /Try again: b\.pdf/ })).toBeInTheDocument();
  expect(chips().queryByRole("button", { name: "Try again" })).toBeNull();
  release();
  await waitFor(() => expect(chips().getAllByRole("listitem")).toHaveLength(2));
  for (const li of chips().getAllByRole("listitem")) {
    expect(li).toHaveAttribute("aria-busy", "false");
  }
});

it("words sizes and problems as Coglossa does", () => {
  expect(sizeText(10)).toBe("1 KB");
  expect(sizeText(1.5 * MB)).toBe("1.5 MB");
  expect(fileProblem(file("a.TXT"), 1)).toBeNull();
  expect(fileProblem(file("README"), 1)).toMatch(/isn't a file type Corelata reads/);
  // the engine reads these too (CRL-109); engine/tests/ingest/test_registry.py pins the list
  expect(fileProblem(file("notes.markdown"), 1)).toBeNull();
  expect(fileProblem(file("page.XHTML"), 1)).toBeNull();
  expect(uploadErrorText(new ApiError(413, "big.txt is larger than the 1 MB upload limit"))).toBe(
    "big.txt is larger than the 1 MB upload limit",
  );
  expect(uploadErrorText(new ApiError(413, errorText(413, null)))).toBe(
    "too large for this server",
  );
  expect(uploadErrorText(new ApiError(422, "x.txt is empty"))).toBe("x.txt is empty");
});

it("shows the drop target while a file is dragged over it", () => {
  renderWithClient(<AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />);
  const area = screen.getByText("Drop files here, or click to choose").closest("label")!;
  fireEvent.dragOver(area);
  expect(area).toHaveClass("over");
  fireEvent.dragLeave(area);
  expect(area).not.toHaveClass("over");
  fireEvent.drop(area, { dataTransfer: { files: [] } });
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});

it("does not send a queued file that was removed while an earlier one uploads, and carries on with the rest", async () => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const order: string[] = [];
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const name = ((await request.formData()).get("file") as File).name;
      order.push(name);
      if (name === "a.txt") await held;
      return HttpResponse.json([{ ...source, id: `id-${name}`, name }], { status: 201 });
    }),
  );
  const added = vi.fn();
  const done = vi.fn();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={added} onDone={done} />,
  );
  await user.upload(screen.getByLabelText("Choose files"), [
    file("a.txt"),
    file("b.txt"),
    file("c.txt"),
  ]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(order).toEqual(["a.txt"]));
  expect(chips().getByRole("button", { name: "Remove a.txt" })).toBeDisabled();
  await user.click(chips().getByRole("button", { name: "Remove c.txt" }));
  release();
  // onDone fires only after the whole batch has run, so a third request would already be in.
  await waitFor(() => expect(done).toHaveBeenCalledTimes(1));
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
  expect(order).toEqual(["a.txt", "b.txt"]);
  expect(added.mock.calls.map(([list]) => list[0].name)).toEqual(["a.txt", "b.txt"]);
});
