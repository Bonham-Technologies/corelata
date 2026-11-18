import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import { project, runSummary, source, sources } from "../test/fixtures";
import type { SourceKind } from "./types";
import { nodeFormData, NodeFileClass } from "../test/node-web";
import { server } from "../test/server";
import {
  useCreateProject,
  useFromCoglossa,
  useProject,
  useProjects,
  useRuns,
  useSources,
  useUploadSource,
} from "./projects";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

it("lists projects, sources and runs", async () => {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(sources)),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      expect(params.get("project_id")).toBe(project.id);
      expect(params.get("limit")).toBe("50");
      expect(params.has("before")).toBe(false); // the first page has no cursor
      return HttpResponse.json({ runs: [runSummary], next_before: null });
    }),
  );
  const projects = renderHook(() => useProjects(), { wrapper });
  await waitFor(() => expect(projects.result.current.data).toEqual([project]));
  const list = renderHook(() => useSources(project.id), { wrapper });
  await waitFor(() => expect(list.result.current.data).toEqual(sources));
  const runs = renderHook(() => useRuns(project.id), { wrapper });
  await waitFor(() =>
    expect(runs.result.current.data?.pages).toEqual([{ runs: [runSummary], next_before: null }]),
  );
  expect(runs.result.current.hasNextPage).toBe(false);
});

it("reads one project, and stays idle without an id", async () => {
  server.use(http.get(`*/api/projects/${project.id}`, () => HttpResponse.json(project)));
  const one = renderHook(() => useProject(project.id), { wrapper });
  await waitFor(() => expect(one.result.current.data).toEqual(project));
  expect(renderHook(() => useProject(null), { wrapper }).result.current.fetchStatus).toBe("idle");
  expect(renderHook(() => useSources(null), { wrapper }).result.current.fetchStatus).toBe("idle");
  expect(renderHook(() => useRuns(null), { wrapper }).result.current.fetchStatus).toBe("idle");
});

it("creates a project and refreshes the list", async () => {
  let posted: unknown;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([])),
    http.post("*/api/projects", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json(project, { status: 201 });
    }),
  );
  const { result } = renderHook(() => useCreateProject(), { wrapper });
  result.current.mutate("Black Sea");
  await waitFor(() => expect(result.current.data).toEqual(project));
  expect(posted).toEqual({ name: "Black Sea" });
});

it("uploads a file as multipart with its kind", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  let received: { name: string; kind: string | null } | undefined;
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      received = { name: (form.get("file") as File).name, kind: form.get("kind") as string };
      return HttpResponse.json([source], { status: 201 });
    }),
  );
  const { result } = renderHook(() => useUploadSource(project.id), { wrapper });
  result.current.mutate({
    file: new File(["Varna"], "port.txt", { type: "text/plain" }),
    kind: "file",
  });
  await waitFor(() => expect(result.current.data).toEqual([source]));
  expect(received).toEqual({ name: "port.txt", kind: "file" });
});

it("imports a Coglossa run by id and surfaces the API's error", async () => {
  server.use(
    http.post(`*/api/projects/${project.id}/sources/from-coglossa`, async ({ request }) => {
      expect(await request.json()).toEqual({ run_id: "run-42" });
      return HttpResponse.json({ detail: "Coglossa run run-42 not found" }, { status: 404 });
    }),
  );
  const { result } = renderHook(() => useFromCoglossa(project.id), { wrapper });
  result.current.mutate("run-42");
  await waitFor(() => expect(result.current.error?.message).toBe("Coglossa run run-42 not found"));
});

it("refreshes the sources after a successful Coglossa import", async () => {
  server.use(
    http.post(`*/api/projects/${project.id}/sources/from-coglossa`, () =>
      HttpResponse.json(sources, { status: 201 }),
    ),
  );
  const { result } = renderHook(() => useFromCoglossa(project.id), { wrapper });
  result.current.mutate("run-42");
  await waitFor(() => expect(result.current.data).toEqual(sources));
});

it("omits an upload field that has no value", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  let keys: string[] = [];
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      keys = [...(await request.formData()).keys()];
      return HttpResponse.json([source], { status: 201 });
    }),
  );
  const { result } = renderHook(() => useUploadSource(project.id), { wrapper });
  result.current.mutate({
    file: new File(["Varna"], "port.txt", { type: "text/plain" }),
    kind: undefined as unknown as SourceKind,
  });
  await waitFor(() => expect(result.current.data).toEqual([source]));
  expect(keys).toEqual(["file"]);
});
