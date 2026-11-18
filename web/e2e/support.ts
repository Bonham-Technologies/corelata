import { expect, type APIRequestContext } from "@playwright/test";

/** The sample source every journey uploads. */
export const PORT_TEXT = [
  "The port of Varna handles grain, containers and general cargo on Bulgaria's Black Sea coast.",
  "A second grain terminal is planned for 2027, doubling the port's grain handling capacity.",
  "Shippers expect waiting times at Varna to fall by a third once the terminal opens.",
].join("\n\n");

export const STATEMENT = "Varna port capacity expansion matters to shippers";

/** Creates a project, uploads PORT_TEXT and starts a run of it through the API. */
export async function startRun(
  request: APIRequestContext,
  { label, maxIterations }: { label: string; maxIterations: number },
) {
  const project = await request.post("/api/projects", { data: { name: `${label} ${Date.now()}` } });
  expect(project.status()).toBe(201);
  const projectId: string = (await project.json()).id;
  const upload = await request.post(`/api/projects/${projectId}/sources`, {
    multipart: {
      file: { name: "port.txt", mimeType: "text/plain", buffer: Buffer.from(PORT_TEXT, "utf-8") },
    },
  });
  expect(upload.status()).toBe(201);
  const [source] = await upload.json();
  const run = await request.post("/api/runs", {
    data: {
      project_id: projectId,
      source_ids: [source.id],
      value_statement: STATEMENT,
      max_iterations: maxIterations,
    },
  });
  expect(run.status()).toBe(202);
  return { projectId, runId: (await run.json()).run_id as string };
}
