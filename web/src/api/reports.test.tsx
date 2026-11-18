import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import {
  claimProvenance,
  findings,
  reportHtml,
  reportJson,
  RUN_ID,
  runTrace,
} from "../test/fixtures";
import { server } from "../test/server";
import { useClaim, useFindings, useReportHtml, useReportJson, useTrace } from "./reports";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

it("reads the report, its JSON, the trace, the findings and a claim", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/report`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      expect(params.get("format")).toBe("html");
      expect(params.get("with_claim_ids")).toBe("true");
      return HttpResponse.text(reportHtml, {
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/claims/c3`, () => HttpResponse.json(claimProvenance)),
  );
  const html = renderHook(() => useReportHtml(RUN_ID), { wrapper });
  await waitFor(() => expect(html.result.current.data).toBe(reportHtml));
  const json = renderHook(() => useReportJson(RUN_ID), { wrapper });
  await waitFor(() => expect(json.result.current.data?.title).toBe(reportJson.title));
  const trace = renderHook(() => useTrace(RUN_ID), { wrapper });
  await waitFor(() => expect(trace.result.current.data?.summary.run_id).toBe(RUN_ID));
  const list = renderHook(() => useFindings(RUN_ID), { wrapper });
  await waitFor(() => expect(list.result.current.data).toHaveLength(3));
  const claim = renderHook(() => useClaim(RUN_ID, "c3"), { wrapper });
  await waitFor(() => expect(claim.result.current.data?.evidence).toHaveLength(2));
  expect(renderHook(() => useClaim(RUN_ID, null), { wrapper }).result.current.fetchStatus).toBe(
    "idle",
  );
});

it("surfaces a 409 for a run without a report", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/report`, () =>
      HttpResponse.json({ detail: `run ${RUN_ID} has no report (state failed)` }, { status: 409 }),
    ),
  );
  const html = renderHook(() => useReportHtml(RUN_ID), { wrapper });
  await waitFor(() => expect(html.result.current.error?.message).toContain("has no report"));
});
