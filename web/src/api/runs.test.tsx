import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { focusManager, type Query } from "@tanstack/react-query";
import { makeQueryClient, Providers } from "../Providers";
import { ApiError } from "./client";
import { projectKeys } from "./projects";
import type { RunProgress } from "./types";
import { noRuns, RUN_ID, runProgress } from "../test/fixtures";
import { server } from "../test/server";
import {
  POLL_MS,
  pollInterval,
  runKeys,
  useCancelRun,
  useReview,
  useRun,
  useStartRun,
} from "./runs";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

describe("pollInterval", () => {
  it("polls only without a live stream, for a known non-terminal run", () => {
    expect(pollInterval(undefined, false, undefined)).toBe(false);
    expect(pollInterval(runProgress({ state: "drafting" }), false, undefined)).toBe(POLL_MS);
    expect(pollInterval(runProgress({ state: "drafting" }), true, undefined)).toBe(false);
    expect(pollInterval(runProgress({ state: "completed" }), false, undefined)).toBe(false);
    expect(pollInterval(undefined, false, new ApiError(404, "gone"))).toBe(false);
    expect(pollInterval(runProgress(), false, new ApiError(503, "down"))).toBe(POLL_MS);
    expect(pollInterval(undefined, false, new ApiError(503, "down"))).toBe(POLL_MS);
  });
});

it("keeps reading a finished run while the rerun its return created has not ended (R-M15-2)", () => {
  const at = "2026-10-18T10:00:00Z";
  const pending = { decision: "returned" as const, at, child_run_id: "c", note: "x" };
  const done = (review: RunProgress["review"]) =>
    pollInterval(runProgress({ state: "completed", review }), false, undefined);
  expect(done(pending)).toBe(POLL_MS);
  expect(done({ ...pending, child_run_id: null })).toBe(POLL_MS); // being created
  expect(done({ ...pending, child_state: "failed" })).toBe(false);
  expect(done({ ...pending, child_state: "completed" })).toBe(false);
  expect(done({ decision: "accepted", at })).toBe(false);
  expect(done(null)).toBe(false);
});

it("reads, starts, cancels and reviews a run", async () => {
  const calls: string[] = [];
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "gating" }))),
    http.post("*/api/runs", async ({ request }) => {
      calls.push(JSON.stringify(await request.json()));
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.post(`*/api/runs/${RUN_ID}/cancel`, () =>
      HttpResponse.json(runProgress({ state: "cancelled", cancel_requested: true })),
    ),
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      calls.push(JSON.stringify(await request.json()));
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const run = renderHook(() => useRun(RUN_ID), { wrapper });
  await waitFor(() => expect(run.result.current.data?.state).toBe("gating"));
  const start = renderHook(() => useStartRun(), { wrapper });
  start.result.current.mutate({
    project_id: "p",
    source_ids: ["s"],
    value_statement: "v",
    extra_guidance: "",
    kind: "report",
  });
  await waitFor(() => expect(start.result.current.data?.state).toBe("created"));
  const cancel = renderHook(() => useCancelRun(RUN_ID), { wrapper });
  cancel.result.current.mutate();
  await waitFor(() => expect(cancel.result.current.data?.state).toBe("cancelled"));
  const review = renderHook(() => useReview(RUN_ID), { wrapper });
  review.result.current.mutate({ action: "accept", note: "" });
  await waitFor(() => expect(review.result.current.data?.action).toBe("accept"));
  expect(calls).toEqual([
    JSON.stringify({
      project_id: "p",
      source_ids: ["s"],
      value_statement: "v",
      extra_guidance: "",
      kind: "report",
    }),
    JSON.stringify({ action: "accept", note: "" }),
  ]);
});

it("returns the child run when a review creates one", async () => {
  const child = runProgress({ run_id: "child-1", parent_run_id: RUN_ID });
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () => HttpResponse.json({ action: "return", child })),
  );
  const review = renderHook(() => useReview(RUN_ID), { wrapper });
  review.result.current.mutate({ action: "return", note: "tighten" });
  await waitFor(() => expect(review.result.current.data?.child?.run_id).toBe("child-1"));
});

it("useRun polls a non-terminal run only when no live stream delivers updates", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
  );
  const client = makeQueryClient({ retry: false });
  const clientWrapper = ({ children }: { children: ReactNode }) => (
    <Providers client={client}>{children}</Providers>
  );
  const intervalFor = async (live: boolean) => {
    client.clear();
    const hook = renderHook(() => useRun(RUN_ID, live), { wrapper: clientWrapper });
    await waitFor(() => expect(hook.result.current.data?.state).toBe("drafting"));
    const query = client.getQueryCache().find({ queryKey: runKeys.one(RUN_ID) })!;
    const option = query.observers[0]!.options.refetchInterval as (q: Query) => unknown;
    hook.unmount();
    return option(query);
  };
  expect(await intervalFor(false)).toBe(POLL_MS);
  expect(await intervalFor(true)).toBe(false);
});

// R-M15-22: a Review page opened before any decision does not poll (nothing is pending), so
// it learns of a decision taken in another tab or by another reviewer when its window is
// focused again. Only the run query refetches on focus; the app's default stays off.
it("the run is re-read when the window regains focus", async () => {
  let reads = 0;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () => {
      reads += 1;
      return HttpResponse.json(runProgress({ state: "completed" }));
    }),
  );
  const client = makeQueryClient({ retry: false });
  const hook = renderHook(() => useRun(RUN_ID), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <Providers client={client}>{children}</Providers>
    ),
  });
  await waitFor(() => expect(hook.result.current.data?.state).toBe("completed"));
  expect(reads).toBe(1);
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => expect(reads).toBe(2));
  focusManager.setFocused(undefined);
  hook.unmount();
});

it("a cancel invalidates the project's run list and the run itself", async () => {
  const client = makeQueryClient({ retry: false });
  const pid = runProgress().project_id;
  client.setQueryData(projectKeys.runs(pid), { pages: [noRuns], pageParams: [null] });
  server.use(
    http.post(`*/api/runs/${RUN_ID}/cancel`, () =>
      HttpResponse.json(runProgress({ state: "drafting", cancel_requested: true })),
    ),
  );
  const cancel = renderHook(() => useCancelRun(RUN_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  cancel.result.current.mutate();
  await waitFor(() => expect(cancel.result.current.data?.cancel_requested).toBe(true));
  expect(client.getQueryState(projectKeys.runs(pid))?.isInvalidated).toBe(true);
  expect(client.getQueryData(runKeys.one(RUN_ID))).toMatchObject({ cancel_requested: true });
});

it("an accepted review refreshes the run so the decision comes from the server", async () => {
  const client = makeQueryClient({ retry: false });
  client.setQueryData(runKeys.one(RUN_ID), runProgress({ state: "completed" }));
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () =>
      HttpResponse.json({ action: "accept", child: null }),
    ),
  );
  const review = renderHook(() => useReview(RUN_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  review.result.current.mutate({ action: "accept", note: "" });
  await waitFor(() => expect(review.result.current.data?.action).toBe("accept"));
  expect(client.getQueryState(runKeys.one(RUN_ID))?.isInvalidated).toBe(true);
});

// The sidebar's project list moves with every change to a report (M18 spec §3.3).
describe("the sidebar's project list is read again", () => {
  const PROJECTS = { queryKey: projectKeys.all, exact: true };
  function setup() {
    const client = makeQueryClient({ retry: false });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrap = ({ children }: { children: ReactNode }) => (
      <Providers client={client}>{children}</Providers>
    );
    return { invalidate, wrap };
  }

  it("after a run starts", async () => {
    const { invalidate, wrap } = setup();
    server.use(http.post("*/api/runs", () => HttpResponse.json(runProgress(), { status: 202 })));
    const start = renderHook(() => useStartRun(), { wrapper: wrap });
    start.result.current.mutate({
      project_id: "p",
      source_ids: ["s"],
      value_statement: "v",
      extra_guidance: "",
      kind: "report",
    });
    await waitFor(() => expect(start.result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith(PROJECTS);
  });

  it("after a cancel", async () => {
    const { invalidate, wrap } = setup();
    server.use(
      http.post(`*/api/runs/${RUN_ID}/cancel`, () =>
        HttpResponse.json(runProgress({ state: "cancelled" })),
      ),
    );
    const cancel = renderHook(() => useCancelRun(RUN_ID), { wrapper: wrap });
    cancel.result.current.mutate();
    await waitFor(() => expect(cancel.result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith(PROJECTS);
  });

  it("after a review", async () => {
    const { invalidate, wrap } = setup();
    server.use(
      http.post(`*/api/runs/${RUN_ID}/review`, () =>
        HttpResponse.json({ action: "accept", child: null }),
      ),
    );
    const review = renderHook(() => useReview(RUN_ID), { wrapper: wrap });
    review.result.current.mutate({ action: "accept", note: "" });
    await waitFor(() => expect(review.result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith(PROJECTS);
  });

  it.each([409, 503])("after a review the server refused with %i", async (status) => {
    const { invalidate, wrap } = setup();
    server.use(
      http.post(`*/api/runs/${RUN_ID}/review`, () =>
        HttpResponse.json({ detail: "moved on" }, { status }),
      ),
    );
    const review = renderHook(() => useReview(RUN_ID), { wrapper: wrap });
    review.result.current.mutate({ action: "accept", note: "" });
    await waitFor(() => expect(review.result.current.isError).toBe(true));
    expect(invalidate).toHaveBeenCalledWith(PROJECTS);
  });

  it("not after a review refused for another reason", async () => {
    const { invalidate, wrap } = setup();
    server.use(
      http.post(`*/api/runs/${RUN_ID}/review`, () =>
        HttpResponse.json({ detail: "bad" }, { status: 400 }),
      ),
    );
    const review = renderHook(() => useReview(RUN_ID), { wrapper: wrap });
    review.result.current.mutate({ action: "accept", note: "" });
    await waitFor(() => expect(review.result.current.isError).toBe(true));
    expect(invalidate).not.toHaveBeenCalledWith(PROJECTS);
  });
});

it("reads the sidebar's project list again when a read, not a stream, sees the run end (CRL-63)", async () => {
  let state: RunProgress["state"] = "drafting";
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state }))));
  const queryClient = makeQueryClient({ retry: false });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const { result } = renderHook(() => useRun(RUN_ID), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <Providers client={queryClient}>{children}</Providers>
    ),
  });
  await waitFor(() => expect(result.current.data?.state).toBe("drafting"));
  const projects = { queryKey: projectKeys.all, exact: true };
  expect(invalidate).not.toHaveBeenCalledWith(projects); // the first read saw no change
  state = "completed";
  await act(() => result.current.refetch());
  expect(invalidate).toHaveBeenCalledWith(projects);
  invalidate.mockClear();
  await act(() => result.current.refetch()); // already ended: nothing more to tell the sidebar
  expect(invalidate).not.toHaveBeenCalledWith(projects);
});
