import type { Query, QueryClient, QueryKey } from "@tanstack/react-query";
import { discoveryKeys } from "../api/discoveries";
import { projectKeys } from "../api/projects";
import { runKeys } from "../api/runs";

/** What the active observer of the query `queryKey` would use as its refetch interval now. */
function refetchInterval(queryClient: QueryClient, queryKey: QueryKey): unknown {
  const query = queryClient.getQueryCache().find({ queryKey })!;
  const option = query.observers[0]!.options.refetchInterval as (q: Query) => unknown;
  return option(query);
}

/** What the run query's active observer would use as its refetch interval right now. */
export function runRefetchInterval(queryClient: QueryClient, runId: string): unknown {
  return refetchInterval(queryClient, runKeys.one(runId));
}

/** The same for the sidebar's project list (M18 spec §3.3). */
export function projectsRefetchInterval(queryClient: QueryClient): unknown {
  return refetchInterval(queryClient, projectKeys.all);
}

/** The same for a discovery's query (R-M16-2, R-M16-3). */
export function discoveryRefetchInterval(queryClient: QueryClient, discoveryId: string): unknown {
  return refetchInterval(queryClient, discoveryKeys.one(discoveryId));
}
