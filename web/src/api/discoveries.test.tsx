import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import {
  candidates,
  deadlineFor,
  DISCOVERY_ID,
  discoveryView,
  minutesAgo,
  project,
  source,
} from "../test/fixtures";
import { discoveryRefetchInterval } from "../test/poll";
import { server } from "../test/server";
import { ApiError } from "./client";
import {
  DISCOVERY_CEILING_MS,
  DISCOVERY_GRACE_MS,
  DISCOVERY_POLL_MAX_MS,
  DISCOVERY_POLL_MS,
  discoveryAge,
  discoveryCeiling,
  discoveryPollInterval,
  discoveryStalled,
  useDiscovery,
  useStartDiscovery,
  type DiscoveryRead,
} from "./discoveries";
import type { DiscoveryView } from "./types";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

function read(overrides: Partial<DiscoveryView> = {}, ageMs = 0): DiscoveryRead {
  return { ...discoveryView(overrides), age_ms: ageMs };
}

function renderDiscovery() {
  const client = makeQueryClient({ retry: false });
  const hook = renderHook(() => useDiscovery(DISCOVERY_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  return { client, hook };
}

it("polls a discovery until it ends, backing off 1, 2, 4 s, then every 5 s (R-M16-3)", () => {
  expect(DISCOVERY_POLL_MAX_MS).toBe(5000);
  expect(discoveryPollInterval(undefined)).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(read({ state: "running" }))).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(read({ state: "completed" }))).toBe(false);
  expect(discoveryPollInterval(read({ state: "failed" }))).toBe(false);
  expect(discoveryPollInterval(undefined, new ApiError(404, "gone"))).toBe(false);
  expect(discoveryPollInterval(undefined, new ApiError(500, "boom"))).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, new Error("network"))).toBe(DISCOVERY_POLL_MS);
  expect([1, 2, 3, 4, 5, 40].map((polls) => discoveryPollInterval(undefined, null, polls))).toEqual(
    [1000, 2000, 4000, 5000, 5000, 5000],
  );
  expect(discoveryPollInterval(read({ state: "completed" }), null, 9)).toBe(false);
});

it("stops polling at the server's deadline plus the grace, and only while it runs (R-M17-1)", () => {
  const ceiling = DISCOVERY_CEILING_MS + DISCOVERY_GRACE_MS; // the default 10-minute deadline
  const justUnder = read({ state: "running" }, ceiling - 1);
  const atCeiling = read({ state: "running" }, ceiling);
  expect(discoveryCeiling(justUnder)).toBe(ceiling);
  expect(discoveryStalled(justUnder)).toBe(false);
  expect(discoveryPollInterval(justUnder, null, 9)).toBe(DISCOVERY_POLL_MAX_MS);
  expect(discoveryStalled(atCeiling)).toBe(true);
  expect(discoveryPollInterval(atCeiling, null, 9)).toBe(false);
  expect(discoveryStalled(read({ state: "created" }, ceiling))).toBe(true);
  // an ended discovery is shown as it ended, however old
  expect(discoveryStalled(read({ state: "completed" }, 2 * ceiling))).toBe(false);
  expect(discoveryStalled(read({ state: "failed" }, 2 * ceiling))).toBe(false);
  expect(discoveryStalled(undefined)).toBe(false);
});

it("follows the configured deadline, but never stops asking sooner than 10 minutes", () => {
  const created = minutesAgo(0);
  const longer = discoveryView({
    created_at: created,
    deadline_at: deadlineFor(created, 1_200_000),
  });
  expect(discoveryCeiling(longer)).toBe(1_200_000 + DISCOVERY_GRACE_MS);
  const shorter = discoveryView({ created_at: created, deadline_at: deadlineFor(created, 60_000) });
  expect(discoveryCeiling(shorter)).toBe(DISCOVERY_CEILING_MS); // the fallback text stays true
  expect(discoveryCeiling(discoveryView({ deadline_at: "not a date" }))).toBe(DISCOVERY_CEILING_MS);
});

it("measures the ceiling from the deadline_at the latest read gives, which the claim moves (R-M17-27)", () => {
  const created = minutesAgo(0);
  // queued: the start limit, an hour after created_at
  const queued = discoveryView({
    created_at: created,
    deadline_at: deadlineFor(created, 3_600_000),
  });
  expect(discoveryCeiling(queued)).toBe(3_600_000 + DISCOVERY_GRACE_MS);
  expect(discoveryStalled({ ...queued, age_ms: 12 * 60_000 })).toBe(false);
  // claimed at minute 9: the work limit, 10 minutes after the claim
  const claimed = discoveryView({
    state: "running",
    created_at: created,
    deadline_at: deadlineFor(created, 19 * 60_000),
  });
  expect(discoveryCeiling(claimed)).toBe(19 * 60_000 + DISCOVERY_GRACE_MS);
  expect(discoveryStalled({ ...claimed, age_ms: 19 * 60_000 })).toBe(false);
  expect(discoveryStalled({ ...claimed, age_ms: 19 * 60_000 + DISCOVERY_GRACE_MS })).toBe(true);
  // claimed at once with a short work limit: never sooner than 10 minutes after created_at
  const early = discoveryView({
    state: "running",
    created_at: created,
    deadline_at: deadlineFor(created, 61_000),
  });
  expect(discoveryCeiling(early)).toBe(DISCOVERY_CEILING_MS);
});

it("measures a discovery's age on the server's clock when the answer carries one", () => {
  const view = discoveryView({ created_at: "2026-10-18T10:00:00.500Z" });
  const now = Date.parse("2026-10-18T10:00:03Z");
  expect(discoveryAge(view, "Sun, 18 Oct 2026 10:11:00 GMT", now)).toBe(659_500);
  expect(discoveryAge(view, null, now)).toBe(2_500); // no header: the browser's clock
  expect(discoveryAge(view, "not a date", now)).toBe(2_500);
});

it("a read of a discovery older than 10 minutes shows it once and does not poll (a reload)", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running", created_at: minutesAgo(11) }));
    }),
  );
  const { client, hook } = renderDiscovery();
  await waitFor(() => expect(hook.result.current.data?.state).toBe("running"));
  expect(hook.result.current.data!.age_ms).toBeGreaterThanOrEqual(DISCOVERY_CEILING_MS);
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(false);
  expect(served).toBe(1);
});

it("a workstation clock that is off does not move the ceiling: the server's Date decides", async () => {
  const created = Date.now();
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(
        discoveryView({ state: "running", created_at: new Date(created).toISOString() }),
        // the server says 11 minutes have passed; this machine's clock says none
        { headers: { Date: new Date(created + 11 * 60_000).toUTCString() } },
      ),
    ),
  );
  const behind = renderDiscovery();
  await waitFor(() => expect(behind.hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(behind.client, DISCOVERY_ID)).toBe(false);

  const ahead = minutesAgo(20); // this machine's clock runs 20 minutes ahead of the server's
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "running", created_at: ahead }), {
        headers: { Date: new Date(Date.parse(ahead) + 30_000).toUTCString() },
      }),
    ),
  );
  const fast = renderDiscovery();
  await waitFor(() => expect(fast.hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(fast.client, DISCOVERY_ID)).toBe(DISCOVERY_POLL_MS);
});

it("useDiscovery counts its polls for the backoff", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running" }));
    }),
  );
  const { client, hook } = renderDiscovery();
  await waitFor(() => expect(hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(DISCOVERY_POLL_MS); // one poll so far
  await hook.result.current.refetch();
  await waitFor(() => expect(served).toBe(2));
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(2 * DISCOVERY_POLL_MS);
});

it("starts a discovery and reads it", async () => {
  server.use(
    http.post("*/api/discoveries", async ({ request }) => {
      expect(await request.json()).toEqual({
        project_id: project.id,
        source_ids: [source.id],
        audience_hint: "ministers",
      });
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const start = renderHook(() => useStartDiscovery(), { wrapper });
  start.result.current.mutate({
    project_id: project.id,
    source_ids: [source.id],
    audience_hint: "ministers",
  });
  await waitFor(() => expect(start.result.current.data?.discovery_id).toBe(DISCOVERY_ID));
  const reader = renderHook(() => useDiscovery(DISCOVERY_ID), { wrapper });
  await waitFor(() => expect(reader.result.current.data?.candidates).toEqual(candidates));
  const idle = renderHook(() => useDiscovery(null), { wrapper });
  expect(idle.result.current.fetchStatus).toBe("idle");
});
