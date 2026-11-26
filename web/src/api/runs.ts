import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isTerminal } from "../lib/format";
import { ApiError, client, unwrap } from "./client";
import { projectKeys, refreshProjects } from "./projects";
import type {
  ClaimMark,
  CreateRun,
  ReviewAction,
  ReviewMarks,
  ReviewResult,
  ReviewState,
  RunProgress,
  RunState,
} from "./types";

export const runKeys = {
  one: (runId: string) => ["runs", runId] as const,
  marks: (runId: string) => ["runs", runId, "marks"] as const,
};

export const POLL_MS = 3000;

/** A rerun that ended in one of these spent nothing: the run can be returned or accepted again
 * (R-M15-1). The server decides by the same states. */
const FREED_BY: ReadonlySet<RunState> = new Set(["gate_rejected", "failed", "cancelled"]);

/** The stored decision is a return whose rerun has not ended yet, so it will change when the
 * rerun ends (R-M15-2). */
export function rerunPending(review: ReviewState | null | undefined): boolean {
  return review?.decision === "returned" && !review.child_state;
}

/** The stored decision is a return whose rerun ended without a report (R-M15-4). */
export function rerunFreed(review: ReviewState | null | undefined): boolean {
  return (
    review?.decision === "returned" && !!review.child_state && FREED_BY.has(review.child_state)
  );
}

/** Poll while the run is live, or its rerun is (a finished run's stream has ended), and no event
 * stream is delivering updates; never after a 404. */
export function pollInterval(
  progress: RunProgress | undefined,
  live: boolean,
  error: unknown,
): number | false {
  if (error instanceof ApiError && error.status === 404) return false; // the run is gone
  if (live) return false;
  if (progress === undefined) return error ? POLL_MS : false;
  return isTerminal(progress.state) && !rerunPending(progress.review) ? false : POLL_MS;
}

function fetchRun(runId: string, signal: AbortSignal): Promise<RunProgress> {
  return unwrap<RunProgress>(
    client.GET("/api/runs/{run_id}", { params: { path: { run_id: runId } }, signal }),
  );
}

/** `live` says whether an event stream delivers the run's updates, so it is not polled; a function
 * decides from the run as last read (the Review page follows a rerun's stream, CRL-77). */
export function useRun(
  runId: string,
  live: boolean | ((run: RunProgress | undefined) => boolean) = false,
) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: runKeys.one(runId),
    queryFn: async ({ signal }) => {
      const run = await fetchRun(runId, signal);
      // A read, not the stream, saw the run end (no stream, or one the browser gave up on): the
      // sidebar's row stops "writing" now rather than on its fallback poll (CRL-63). After a
      // stream's terminal event the cached run has already ended, so this does not repeat it.
      const before = queryClient.getQueryData<RunProgress>(runKeys.one(runId));
      if (before && !isTerminal(before.state) && isTerminal(run.state)) {
        void refreshProjects(queryClient);
      }
      return run;
    },
    refetchInterval: (query) =>
      pollInterval(
        query.state.data,
        typeof live === "function" ? live(query.state.data) : live,
        query.state.error,
      ),
    // R-M15-22: a page with nothing pending does not poll, so a decision taken in another tab
    // or by another reviewer shows when this window is focused again (the app default is off).
    refetchOnWindowFocus: true,
  });
}

/** The run a new report starts from (CRL-84), read once and not polled; nothing while `runId`
 * is null. It shares the run's own entry, so a link from the run's page fills the form at once. */
export function useEarlierRun(runId: string | null) {
  return useQuery({
    queryKey: runKeys.one(runId ?? ""),
    queryFn: runId === null ? skipToken : ({ signal }) => fetchRun(runId, signal),
  });
}

export function useStartRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateRun) => unwrap<RunProgress>(client.POST("/api/runs", { body })),
    onSuccess: (run) => {
      queryClient.setQueryData(runKeys.one(run.run_id), run);
      void queryClient.invalidateQueries({ queryKey: projectKeys.runs(run.project_id) });
      void refreshProjects(queryClient);
    },
  });
}

export function useCancelRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap<RunProgress>(
        client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(runKeys.one(runId), run);
      void queryClient.invalidateQueries({ queryKey: projectKeys.runs(run.project_id) });
      void refreshProjects(queryClient);
    },
  });
}

/** Each claim's review mark and the counts shown before Accept (CRL-139); nothing while
 * `enabled` is false (a checked report has no review). */
export function useReviewMarks(runId: string, enabled = true) {
  return useQuery({
    queryKey: runKeys.marks(runId),
    queryFn: ({ signal }) =>
      unwrap<ReviewMarks>(
        client.GET("/api/runs/{run_id}/marks", { params: { path: { run_id: runId } }, signal }),
      ),
    enabled,
  });
}

/** Mark a claim checked or disputed (CRL-139); the answer is the run's marks as they now stand.
 * A refusal (409: the run was accepted or returned meanwhile) re-reads them. */
export function useMarkClaim(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { claimId: string; mark: ClaimMark; comment: string }) =>
      unwrap<ReviewMarks>(
        client.PUT("/api/runs/{run_id}/marks/{claim_id}", {
          params: { path: { run_id: runId, claim_id: body.claimId } },
          body: { mark: body.mark, comment: body.comment },
        }),
      ),
    onSuccess: (marks) => queryClient.setQueryData(runKeys.marks(runId), marks),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: runKeys.marks(runId), exact: true });
      }
    },
  });
}

export function useReview(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { action: ReviewAction; note: string }) =>
      unwrap<ReviewResult>(
        client.POST("/api/runs/{run_id}/review", { params: { path: { run_id: runId } }, body }),
      ),
    onSuccess: (result) => {
      // The decision now lives on the server (RunProgress.review): refetch the run, exactly.
      // Because the promise is returned, the mutation stays pending until that refetch lands, so Accept and Return
      // cannot re-enable for a round trip.
      const refetched = queryClient.invalidateQueries({
        queryKey: runKeys.one(runId),
        exact: true,
      });
      // A decision closes the marks (CRL-139): they read as final from now on.
      void queryClient.invalidateQueries({ queryKey: runKeys.marks(runId), exact: true });
      if (result.child) {
        queryClient.setQueryData(runKeys.one(result.child.run_id), result.child);
        void queryClient.invalidateQueries({ queryKey: projectKeys.runs(result.child.project_id) });
      }
      void refreshProjects(queryClient); // the sidebar's "waiting for review" count moved
      return refetched;
    },
    onError: (error) => {
      // Refused because the run moved on (another reviewer's return won, or the queue refused): the page
      // is stale, so re-read it. The error itself still reaches the caller.
      if (error instanceof ApiError && (error.status === 409 || error.status === 503)) {
        void refreshProjects(queryClient); // the sidebar's count may be stale too
        // An accept the profile refused (CRL-139) may rest on marks another reviewer changed.
        void queryClient.invalidateQueries({ queryKey: runKeys.marks(runId), exact: true });
        return queryClient.invalidateQueries({ queryKey: runKeys.one(runId), exact: true });
      }
    },
  });
}
