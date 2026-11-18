import { useQuery } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import type { PackSummary, ResolvedPack } from "./types";

export const packKeys = {
  all: ["packs"] as const,
  resolved: (name: string, profile: string | null) => ["packs", name, "resolved", profile] as const,
};

/** The Audit tab resolves the run's pack on every review open; a customer edit shows within this
 * long (CRL-8). The pack listing (`usePacks`) keeps its minute: the New run screen picks from it. */
export const RESOLVED_PACK_STALE_MS = 10 * 60_000;

export function usePacks() {
  return useQuery({
    queryKey: packKeys.all,
    queryFn: ({ signal }) => unwrap<PackSummary[]>(client.GET("/api/packs", { signal })),
    staleTime: 60_000,
  });
}

export function useResolvedPack(name: string | null, profile: string | null) {
  return useQuery({
    queryKey: packKeys.resolved(name ?? "", profile),
    queryFn: ({ signal }) =>
      unwrap<ResolvedPack>(
        client.GET("/api/packs/{name}/resolved", {
          params: { path: { name: name! }, query: profile ? { profile } : {} },
          signal,
        }),
      ),
    enabled: name !== null,
    staleTime: RESOLVED_PACK_STALE_MS,
  });
}
