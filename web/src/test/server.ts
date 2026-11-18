import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { info, reportJson } from "./fixtures";

// Every page renders the layout, which asks who is signed in and which version answers, and
// the sidebar, which lists the projects (none, unless a test serves some). A completed run's
// page reads its report's title for the browser tab (M18 spec §3.4).
export const server = setupServer(
  http.get("*/api/system/info", () => HttpResponse.json(info)),
  http.get("*/api/projects", () => HttpResponse.json([])),
  http.get("*/api/runs/:runId/exports/report.json", () => HttpResponse.json(reportJson)),
);
