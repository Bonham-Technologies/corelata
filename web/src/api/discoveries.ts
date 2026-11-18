import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, client, unwrap } from "./client";
import type { DiscoveryView } from "./types";

export const discoveryKeys = { one: (id: string) => ["discoveries", id] as const };
export const DISCOVERY_POLL_MS = 1000;
export const DISCOVERY_POLL_MAX_MS = 5000;
/** The screen never stops asking sooner than this (CRL-21, R-M16-2), so the fallback message
 * below is always true. */
export const DISCOVERY_CEILING_MS = 10 * 60_000;
/** How long past the server's `deadline_at` the screen keeps asking, so that at least one read
 * lands after the server failed the discovery and the screen shows the server's reason
 * (R-M17-1). */
export const DISCOVERY_GRACE_MS = 15_000;
/** Shown only when the server did not end a discovery by its deadline (a clock that is off, or a
 * server that does not enforce one). */
export const DISCOVERY_STALLED =
  "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.";

/** A discovery as one read saw it, with how old it was then: the time on the server's clock
 * (the answer's `Date` header) minus its `created_at`, so neither a reload nor a workstation
 * clock that is off moves the ceiling (R-M16-15). Without the header, the browser's clock. */
export type DiscoveryRead = DiscoveryView & { age_ms: number };

export function discoveryAge(view: DiscoveryView, serverDate: string | null, now: number): number {
  const at = serverDate ? Date.parse(serverDate) : Number.NaN;
  return (Number.isNaN(at) ? now : at) - Date.parse(view.created_at);
}

function ended(view: DiscoveryView | undefined): boolean {
  return view?.state === "completed" || view?.state === "failed";
}

/** How old a discovery may be, by the server's clock, before the screen stops asking: until
 * DISCOVERY_GRACE_MS past the `deadline_at` of the latest read, and at least
 * DISCOVERY_CEILING_MS after `created_at` (R-M17-1, R-M17-27). `deadline_at` is the limit that
 * applies now: the start limit while the discovery waits for the worker, the work limit from the
 * claim on, so the ceiling moves with the claim; both stamps are the server's, and the age it is
 * compared with is measured on the server's clock (R-M16-15). */
export function discoveryCeiling(view: DiscoveryView): number {
  const deadline = Date.parse(view.deadline_at) - Date.parse(view.created_at);
  if (Number.isNaN(deadline)) return DISCOVERY_CEILING_MS;
  return Math.max(DISCOVERY_CEILING_MS, deadline + DISCOVERY_GRACE_MS);
}

/** Still running past its ceiling, as of the latest read (R-M16-2, R-M17-1). */
export function discoveryStalled(view: DiscoveryRead | undefined): boolean {
  return view !== undefined && !ended(view) && view.age_ms >= discoveryCeiling(view);
}

/** 1 s, 2 s, 4 s, then every 5 s (R-M9-9, R-M16-3), until the discovery ends or passes its
 * ceiling (R-M17-1). `polls` is how many answers (or failures) the query has had so far. */
export function discoveryPollInterval(
  view: DiscoveryRead | undefined,
  error: Error | null = null,
  polls = 0,
): number | false {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  if (ended(view) || discoveryStalled(view)) return false;
  return Math.min(DISCOVERY_POLL_MS * 2 ** Math.max(0, polls - 1), DISCOVERY_POLL_MAX_MS);
}

/** No audience hint: leave the field out rather than send "" (R-M17-6); the server's default is
 * "" either way. */
export type StartDiscovery = { project_id: string; source_ids: string[]; audience_hint?: string };

export function useStartDiscovery() {
  return useMutation({
    mutationFn: (body: StartDiscovery) =>
      unwrap<DiscoveryView>(
        // the generated type marks a field with a server default as required
        client.POST("/api/discoveries", { body: body as Required<StartDiscovery> }),
      ),
  });
}

/** A discovery takes a few seconds; there is no event stream for it, so poll until it ends. */
export function useDiscovery(discoveryId: string | null) {
  return useQuery({
    queryKey: discoveryKeys.one(discoveryId ?? ""),
    queryFn: async ({ signal }): Promise<DiscoveryRead> => {
      let date: string | null = null;
      const view = await unwrap<DiscoveryView>(
        client
          .GET("/api/discoveries/{discovery_id}", {
            params: { path: { discovery_id: discoveryId! } },
            signal,
          })
          .then((result) => {
            date = result.response.headers.get("date");
            return result;
          }),
      );
      return { ...view, age_ms: discoveryAge(view, date, Date.now()) };
    },
    enabled: discoveryId !== null,
    refetchInterval: (query) =>
      discoveryPollInterval(
        query.state.data,
        query.state.error,
        query.state.dataUpdateCount + query.state.fetchFailureCount,
      ),
  });
}
