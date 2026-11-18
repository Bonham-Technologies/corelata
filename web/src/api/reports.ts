import { useQuery } from "@tanstack/react-query";
import { client, exportUrl, reportUrl, unwrap, unwrapText } from "./client";
import type { ClaimProvenance, Finding, ReportJson, RunTrace } from "./types";

export const reportKeys = {
  html: (runId: string) => ["runs", runId, "report", "html"] as const,
  json: (runId: string) => ["runs", runId, "report", "json"] as const,
  trace: (runId: string) => ["runs", runId, "trace"] as const,
  findings: (runId: string) => ["runs", runId, "findings"] as const,
  claim: (runId: string, claimId: string) => ["runs", runId, "claims", claimId] as const,
};

// Every query passes TanStack Query's `signal`, so leaving the page cancels what it was still
// loading instead of finishing it for nobody (CRL-40).

/** The rendered report with claim ids on (spec §9: default on for HTML in the review UI). */
export function useReportHtml(runId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.html(runId),
    queryFn: ({ signal }) => unwrapText(reportUrl(runId, "html", { claimIds: true }), signal),
    staleTime: Infinity,
    enabled,
  });
}

export function useReportJson(runId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.json(runId),
    queryFn: async ({ signal }) =>
      JSON.parse(await unwrapText(exportUrl(runId, "report.json"), signal)) as ReportJson,
    staleTime: Infinity,
    enabled,
  });
}

export function useTrace(runId: string) {
  return useQuery({
    queryKey: reportKeys.trace(runId),
    queryFn: ({ signal }) =>
      unwrap<RunTrace>(
        client.GET("/api/runs/{run_id}/trace", { params: { path: { run_id: runId } }, signal }),
      ),
    staleTime: Infinity,
  });
}

export function useFindings(runId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.findings(runId),
    enabled,
    queryFn: ({ signal }) =>
      unwrap<Finding[]>(
        client.GET("/api/runs/{run_id}/findings", {
          params: { path: { run_id: runId } },
          signal,
        }),
      ),
    staleTime: Infinity,
  });
}

export function useClaim(runId: string, claimId: string | null) {
  return useQuery({
    queryKey: reportKeys.claim(runId, claimId ?? ""),
    queryFn: ({ signal }) =>
      unwrap<ClaimProvenance>(
        client.GET("/api/runs/{run_id}/claims/{claim_id}", {
          params: { path: { run_id: runId, claim_id: claimId! } },
          signal,
        }),
      ),
    enabled: claimId !== null,
    staleTime: Infinity,
  });
}
