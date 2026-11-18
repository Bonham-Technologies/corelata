import {
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { client, unwrap } from "./client";
import type { ProjectView, RunPage, SourceKind, SourceView } from "./types";

export const projectKeys = {
  all: ["projects"] as const,
  one: (id: string) => ["projects", id] as const,
  sources: (id: string) => ["projects", id, "sources"] as const,
  runs: (id: string) => ["projects", id, "runs"] as const,
};

/** How often the project list is read again while a report is being written that no run event
 * stream open on this client follows (M18 spec §3.3, CRL-63). */
export const PROJECTS_POLL_MS = 30_000;

/** The run event streams open on one query client (`useRunEvents`). Each reports its run's end
 * and the project list is read again then, so the list is not polled for the runs they follow. */
class RunStreams {
  #open = 0;
  readonly #listeners = new Set<() => void>();

  readonly subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  readonly count = (): number => this.#open;

  /** Counts one more open stream until the returned release is called; calling it again does
   * nothing, so every way a stream closes may call it. */
  opened(): () => void {
    this.#change(1);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.#change(-1);
    };
  }

  #change(by: number): void {
    this.#open += by;
    for (const listener of this.#listeners) listener();
  }
}

const runStreams = new WeakMap<QueryClient, RunStreams>();

function streamsOf(queryClient: QueryClient): RunStreams {
  let streams = runStreams.get(queryClient);
  if (streams === undefined) {
    streams = new RunStreams();
    runStreams.set(queryClient, streams);
  }
  return streams;
}

/** `useRunEvents` calls this when it opens a run's stream, and the release when it closes it. */
export function runStreamOpened(queryClient: QueryClient): () => void {
  return streamsOf(queryClient).opened();
}

/** Every project with its summary: the sidebar's list (M18 spec §3.3). Read again when the window
 * regains focus, after a change that adds a project, a source, a report or a decision
 * (`refreshProjects`), and when an open run stream reports the run's end or its deletion
 * (`useRunEvents`) or a read of the run sees it end (`useRun`): the only changes of a run the
 * sidebar shows, since a run is "writing" at every stage. While more reports are being written
 * than streams are open (none open after a reload onto a page that follows no run or a stream
 * the browser gave up on, or a run no stream follows) it is read every `PROJECTS_POLL_MS`;
 * nothing else polls it (CRL-63). */
export function useProjects() {
  const queryClient = useQueryClient();
  const streams = streamsOf(queryClient);
  const streamsOpen = useSyncExternalStore(streams.subscribe, streams.count);
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: ({ signal }) => unwrap<ProjectView[]>(client.GET("/api/projects", { signal })),
    refetchOnWindowFocus: true,
    // Poll only for runs no open stream follows: one started earlier, in another tab or by
    // another analyst keeps writing while this page streams a different run.
    refetchInterval: (query) =>
      (query.state.data ?? []).reduce((n, p) => n + p.reports_writing, 0) > streamsOpen
        ? PROJECTS_POLL_MS
        : false,
  });
}

/** The project list only, not each project's sources or runs (those keys start the same). */
export function refreshProjects(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: projectKeys.all, exact: true });
}

export function useProject(projectId: string | null) {
  return useQuery({
    queryKey: projectKeys.one(projectId ?? ""),
    queryFn: ({ signal }) =>
      unwrap<ProjectView>(
        client.GET("/api/projects/{project_id}", {
          params: { path: { project_id: projectId! } },
          signal,
        }),
      ),
    enabled: projectId !== null,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap<ProjectView>(client.POST("/api/projects", { body: { name } })),
    onSuccess: () => refreshProjects(queryClient),
  });
}

export function useSources(projectId: string | null) {
  return useQuery({
    queryKey: projectKeys.sources(projectId ?? ""),
    queryFn: ({ signal }) =>
      unwrap<SourceView[]>(
        client.GET("/api/projects/{project_id}/sources", {
          params: { path: { project_id: projectId! } },
          signal,
        }),
      ),
    enabled: projectId !== null,
  });
}

export type Upload = { file: File; kind: SourceKind };

export function useUploadSource(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (upload: Upload) =>
      unwrap<SourceView[]>(
        client.POST("/api/projects/{project_id}/sources", {
          params: { path: { project_id: projectId } },
          // The generated type calls the file a string (binary form field); FormData carries it.
          body: { file: upload.file as unknown as string, kind: upload.kind },
          bodySerializer(body) {
            const form = new FormData();
            for (const [key, value] of Object.entries(body)) {
              if (value === null || value === undefined) continue;
              // typeof, not instanceof Blob: the file may come from another realm (tests).
              if (typeof value === "object") form.append(key, value as Blob);
              else form.append(key, String(value));
            }
            return form; // no Content-Type: the browser adds the multipart boundary
          },
        }),
      ),
    onSuccess: () => {
      void refreshProjects(queryClient);
      return queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) });
    },
  });
}

export function useFromCoglossa(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap<SourceView[]>(
        client.POST("/api/projects/{project_id}/sources/from-coglossa", {
          params: { path: { project_id: projectId } },
          body: { run_id: runId },
        }),
      ),
    onSuccess: () => {
      void refreshProjects(queryClient);
      return queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) });
    },
  });
}

export const RUN_PAGE = 50;

/** A project's runs, newest first, `RUN_PAGE` at a time: each next page continues after the last
 * run shown, by the cursor the API returned with the page before (R-M14-1), so a project of any
 * size can be paged to its oldest run. The key is `projectKeys.runs(id)`: a mutation that
 * invalidates it refetches every loaded page. */
export function useRuns(projectId: string | null) {
  return useInfiniteQuery({
    queryKey: projectKeys.runs(projectId ?? ""),
    queryFn: ({ pageParam, signal }) =>
      unwrap<RunPage>(
        client.GET("/api/runs", {
          params: {
            query: {
              project_id: projectId!,
              limit: RUN_PAGE,
              ...(pageParam === null ? {} : { before: pageParam }),
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: RunPage) => last.next_before,
    enabled: projectId !== null,
  });
}
