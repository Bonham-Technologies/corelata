import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import { FakeEventSource } from "../test/fake-events";
import { project, RUN_ID, runProgress } from "../test/fixtures";
import { server } from "../test/server";
import { PROJECTS_POLL_MS, projectKeys, useProjects } from "./projects";
import { liveUpdatesAvailable, setEventSourceFactory, useRunEvents } from "./events";
import { runKeys } from "./runs";

beforeEach(() => {
  FakeEventSource.instances = [];
  setEventSourceFactory((url) => new FakeEventSource(url));
});
afterEach(() => setEventSourceFactory(undefined));

function setup(active = true, onStreamFailed?: () => void) {
  const queryClient = makeQueryClient({ retry: false });
  queryClient.setQueryData(runKeys.one(RUN_ID), runProgress());
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Providers client={queryClient}>{children}</Providers>
  );
  const hook = renderHook(() => useRunEvents(RUN_ID, active, onStreamFailed), { wrapper });
  return { queryClient, hook };
}

it("knows whether live updates are available", () => {
  expect(liveUpdatesAvailable()).toBe(true);
  setEventSourceFactory(null);
  expect(liveUpdatesAvailable()).toBe(false);
  setEventSourceFactory(undefined);
  expect(liveUpdatesAvailable()).toBe(typeof EventSource !== "undefined");
});

it("writes each progress event into the cache and closes after a terminal one", async () => {
  const { queryClient } = setup();
  const source = FakeEventSource.last();
  expect(source.url).toBe(`/api/runs/${RUN_ID}/events`);
  source.emit("progress", runProgress({ state: "gating" }));
  await waitFor(() =>
    expect(queryClient.getQueryData(runKeys.one(RUN_ID))).toMatchObject({ state: "gating" }),
  );
  expect(source.closed).toBe(false);
  source.emit("progress", runProgress({ state: "completed", status: "clean" }));
  await waitFor(() => expect(source.closed).toBe(true));
  expect(queryClient.getQueryData(runKeys.one(RUN_ID))).toMatchObject({ state: "completed" });
});

it("reads the sidebar's project list again when the stream reports a terminal state, not before", async () => {
  const { queryClient } = setup();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const projects = { queryKey: projectKeys.all, exact: true };
  const source = FakeEventSource.last();
  source.emit("progress", runProgress({ state: "drafting" }));
  await waitFor(() =>
    expect(queryClient.getQueryData(runKeys.one(RUN_ID))).toMatchObject({ state: "drafting" }),
  );
  expect(invalidate).not.toHaveBeenCalledWith(projects);
  source.emit("progress", runProgress({ state: "completed", status: "clean" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith(projects));
});

it("closes on deleted and refetches so the page sees the 404 and the sidebar its counts", async () => {
  const { queryClient } = setup();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  FakeEventSource.last().emit("deleted", {});
  await waitFor(() => expect(FakeEventSource.last().closed).toBe(true));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: runKeys.one(RUN_ID), exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: projectKeys.all, exact: true });
});

it("reports a stream the browser gave up on, and ignores recoverable errors", () => {
  const failed = vi.fn();
  setup(true, failed);
  const source = FakeEventSource.last();
  source.listeners.get("error")?.({ data: "" } as MessageEvent<string>); // readyState 1: reconnecting
  expect(failed).not.toHaveBeenCalled();
  source.fail();
  expect(failed).toHaveBeenCalledTimes(1);
  expect(source.closed).toBe(true);
});

it("opens nothing when inactive or without EventSource, and closes on unmount", () => {
  setup(false);
  expect(FakeEventSource.instances).toHaveLength(0);
  setEventSourceFactory(null);
  setup(true);
  expect(FakeEventSource.instances).toHaveLength(0);
  setEventSourceFactory((url) => new FakeEventSource(url));
  const { hook } = setup(true);
  hook.unmount();
  expect(FakeEventSource.last().closed).toBe(true);
});

it("uses the browser's EventSource when one exists", () => {
  const constructed: string[] = [];
  class BrowserEventSource {
    readyState = 1;
    constructor(url: string) {
      constructed.push(url);
    }
    addEventListener() {}
    close() {}
  }
  vi.stubGlobal("EventSource", BrowserEventSource);
  try {
    setEventSourceFactory(undefined);
    setup(true);
    expect(constructed).toEqual([`/api/runs/${RUN_ID}/events`]);
  } finally {
    vi.unstubAllGlobals();
  }
});

describe("the sidebar's project list follows the stream, not a timer (CRL-63)", () => {
  let requests = 0;
  let writing = 1;

  beforeEach(() => {
    requests = 0;
    writing = 1;
    server.use(
      http.get("*/api/projects", () => {
        requests += 1;
        return HttpResponse.json([{ ...project, reports_writing: writing }]);
      }),
    );
    // Only the timers TanStack Query polls with: msw and React keep their own scheduling.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  });
  afterEach(() => vi.useRealTimers());

  const OTHER_RUN = "99999999-9999-9999-9999-999999999999";
  type Open = { first: boolean; second: boolean };

  /** The sidebar's list and up to two runs' streams on one client, each open while `open` says. */
  async function follow(open: Open) {
    const queryClient = makeQueryClient({ retry: false });
    queryClient.setQueryData(runKeys.one(RUN_ID), runProgress());
    const wrapper = ({ children }: { children: ReactNode }) => (
      <Providers client={queryClient}>{children}</Providers>
    );
    const hook = renderHook(
      ({ first, second }: Open) => {
        useRunEvents(RUN_ID, first);
        useRunEvents(OTHER_RUN, second);
        return useProjects();
      },
      { wrapper, initialProps: open },
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    await vi.waitFor(() => expect(hook.result.current.data).toBeDefined());
    expect(requests).toBe(1);
    return { queryClient, hook };
  }

  const after = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  it("reads nothing on a timer while a run's stream is open, and once when it ends", async () => {
    await follow({ first: true, second: false });
    await after(25_000);
    expect(requests).toBe(1);
    await after(60_000); // past the fallback interval too
    expect(requests).toBe(1);
    writing = 0;
    act(() =>
      FakeEventSource.last().emit("progress", runProgress({ state: "completed", status: "clean" })),
    );
    await vi.waitFor(() => expect(requests).toBe(2));
    await after(120_000); // nothing is writing now: no poll at all
    expect(requests).toBe(2);
  });

  it("reads nothing for a stage change: only the run's end changes the sidebar's status", async () => {
    await follow({ first: true, second: false });
    act(() => FakeEventSource.last().emit("progress", runProgress({ state: "drafting" })));
    await after(1_000);
    expect(requests).toBe(1);
  });

  it("falls back to a poll of at least 30 s with no stream, only while a report is writing", async () => {
    expect(PROJECTS_POLL_MS).toBeGreaterThanOrEqual(30_000);
    // vi.waitFor advances the fake clock a little: hence the second's slack below
    await follow({ first: false, second: false });
    await after(PROJECTS_POLL_MS - 1_000);
    expect(requests).toBe(1);
    await after(1_000);
    await vi.waitFor(() => expect(requests).toBe(2));
    writing = 0;
    await after(PROJECTS_POLL_MS);
    await vi.waitFor(() => expect(requests).toBe(3));
    await after(3 * PROJECTS_POLL_MS);
    expect(requests).toBe(3);
  });

  it("still polls for a run no stream follows while another run streams", async () => {
    writing = 2; // a run started earlier, or in another tab, keeps writing unfollowed
    await follow({ first: true, second: false });
    await after(PROJECTS_POLL_MS - 1_000);
    expect(requests).toBe(1);
    await after(1_000);
    await vi.waitFor(() => expect(requests).toBe(2));
    writing = 1; // that run ended: only the streamed one is writing, and its stream follows it
    await after(PROJECTS_POLL_MS);
    await vi.waitFor(() => expect(requests).toBe(3));
    await after(3 * PROJECTS_POLL_MS);
    expect(requests).toBe(3);
  });

  it("polls again once every stream is closed, by failure or by leaving the page", async () => {
    const { hook } = await follow({ first: true, second: true });
    const [first, second] = FakeEventSource.instances;
    act(() => first!.fail()); // the browser gave up: that stream no longer delivers anything
    act(() => first!.fail()); // a second report of the same failure counts once
    await after(2 * PROJECTS_POLL_MS);
    expect(requests).toBe(1); // the other run still streams
    expect(second!.closed).toBe(false);
    hook.rerender({ first: true, second: false });
    expect(second!.closed).toBe(true);
    await after(PROJECTS_POLL_MS);
    await vi.waitFor(() => expect(requests).toBe(2));
  });
});
