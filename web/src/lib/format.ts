import type { RunState } from "../api/types";

/** The pipeline's stages in order (spec §7.2); drafting, conveying and auditing repeat per
 * iteration. */
export const STAGES = [
  "ingesting",
  "gating",
  "drafting",
  "conveying",
  "auditing",
  "rendering",
] as const;
export type Stage = (typeof STAGES)[number];

export const TERMINAL_STATES: ReadonlySet<RunState> = new Set<RunState>([
  "completed",
  "gate_rejected",
  "failed",
  "cancelled",
]);

export function isTerminal(state: RunState): boolean {
  return TERMINAL_STATES.has(state);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

export function durationBetween(start: string, end: string | null | undefined): number | null {
  if (!end) return null;
  return Math.max(0, new Date(end).getTime() - new Date(start).getTime());
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function formatInt(n: number): string {
  return n.toLocaleString();
}

/** "c1, c3" → ["c1", "c3"]; the report's data-claim-ids are space-separated. */
export function splitIds(value: string | null | undefined): string[] {
  return (value ?? "").split(/\s+/).filter(Boolean);
}
