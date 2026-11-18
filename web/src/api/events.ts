import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { isTerminal } from "../lib/format";
import { eventsUrl } from "./client";
import { refreshProjects, runStreamOpened } from "./projects";
import { runKeys } from "./runs";
import type { RunProgress } from "./types";

export type EventSourceLike = {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
};
export type EventSourceFactory = (url: string) => EventSourceLike;

const EVENT_SOURCE_CLOSED = 2;

let override: EventSourceFactory | null | undefined;

/** Tests replace the browser's EventSource; `undefined` restores it, `null` turns it off. */
export function setEventSourceFactory(factory?: EventSourceFactory | null): void {
  override = factory;
}

function factory(): EventSourceFactory | null {
  if (override !== undefined) return override;
  if (typeof EventSource === "undefined") return null;
  return (url) => new EventSource(url);
}

export function liveUpdatesAvailable(): boolean {
  return factory() !== null;
}

/** Spec §10.3 Progress: follow a run over server-sent events while it runs. The server closes
 * the stream after the terminal event; the client closes too, or a browser would reconnect
 * forever (docs/m4a-followups.md). While the stream is open the sidebar's project list is not
 * polled for this run: it is read again when the stream reports the run's end or its deletion
 * (M18 spec §3.3, CRL-63). `onEnded` is told of either: the Review page then reads the run whose
 * rerun this is (CRL-77). */
export function useRunEvents(
  runId: string,
  active: boolean,
  onStreamFailed?: () => void,
  onEnded?: () => void,
): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    const open = factory();
    if (!active || open === null) return;
    const source = open(eventsUrl(runId));
    const release = runStreamOpened(queryClient);
    const close = () => {
      source.close();
      release();
    };
    source.addEventListener("progress", (event) => {
      const progress = JSON.parse(event.data) as RunProgress;
      queryClient.setQueryData<RunProgress>(runKeys.one(runId), progress);
      if (isTerminal(progress.state)) {
        close();
        void refreshProjects(queryClient); // the sidebar's row stops "writing" (M18 spec §3.3)
        onEnded?.();
      }
    });
    source.addEventListener("deleted", () => {
      close();
      void queryClient.invalidateQueries({ queryKey: runKeys.one(runId), exact: true });
      void refreshProjects(queryClient); // the run no longer counts in the sidebar
      onEnded?.();
    });
    // The browser reconnects by itself unless it gave up (readyState CLOSED, e.g. a 502):
    // then the page falls back to polling, and so does the sidebar's list.
    source.addEventListener("error", () => {
      if (source.readyState !== EVENT_SOURCE_CLOSED) return;
      close();
      onStreamFailed?.();
    });
    return close;
  }, [runId, active, queryClient, onStreamFailed, onEnded]);
}
