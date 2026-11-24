import type { ClaimKind, ReportStatus, RunState, Severity, Verdict } from "../api/types";

/** The words the screens use for the engine's (M18 spec §4). The engine's own words stay in the
 * API, the CLI, the trace, the Process and Sources tabs and Settings ▸ Technical details (§4.4).
 * words.test.ts checks that every value the API can send has a word here. */

/** §4.3: a run's state as a step of writing the report. The last three are not steps but
 * outcomes; the Process tab names a stage with these words. */
export const STEP_LABEL: Record<RunState, string> = {
  created: "Waiting to start",
  ingesting: "Reading the sources",
  gating: "Checking the value statement",
  structuring: "Reading the report",
  drafting: "Drafting",
  conveying: "Editing for the reader",
  auditing: "Checking against the standards",
  rendering: "Preparing the documents",
  completed: "Ready to review",
  gate_rejected: "Not supported by the sources",
  failed: "Couldn't finish",
  cancelled: "Stopped",
};

/** The steps the writing page lists, in order (§4.3, §5.3). */
export const PROGRESS_STEPS = [
  "created",
  "ingesting",
  "gating",
  "drafting",
  "conveying",
  "auditing",
  "rendering",
  "completed",
] as const satisfies readonly RunState[];

/** The steps a check of a finished report lists (CRL-94): no value check, drafting or editing. */
export const CHECK_STEPS = [
  "created",
  "ingesting",
  "structuring",
  "auditing",
  "rendering",
  "completed",
] as const satisfies readonly RunState[];
export type ProgressStep = (typeof PROGRESS_STEPS)[number] | (typeof CHECK_STEPS)[number];

/** Drafting, editing and checking repeat on a revision (§4.3). */
export const REVISED_STEPS: ReadonlySet<RunState> = new Set<RunState>([
  "drafting",
  "conveying",
  "auditing",
]);

/** §4.1: a rule's verdict, with its symbol. */
export const VERDICT: Record<Verdict, { symbol: string; text: string }> = {
  fail: { symbol: "✗", text: "not met" },
  pass: { symbol: "✓", text: "met" },
  not_applicable: { symbol: "–", text: "doesn't apply" },
  attested: { symbol: "◇", text: "attested" },
};

export const SEVERITY: Record<Severity, string> = {
  blocking: "Blocking",
  major: "Major",
  minor: "Minor",
};

/** A finding carries its rule's severity as text: the pack's words, capitalised. */
export function severityText(severity: string): string {
  const known = (SEVERITY as Record<string, string | undefined>)[severity];
  return known ?? severity.charAt(0).toUpperCase() + severity.slice(1);
}

export const CLAIM_KIND: Record<ClaimKind, string> = {
  fact: "Fact",
  judgment: "Judgment",
  assumption: "Assumption",
};

/** A report's status while it waits for a decision. One place, so the sidebar, the writing page
 * and Help say it the same way. */
export const WAITING_FOR_REVIEW = "waiting for review";

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "key_judgments[0]" → "Key judgments, item 1"; "analysis[0].paragraphs[1]" → "Analysis,
 * section 1, paragraph 2"; "alternatives[0]" → "Alternatives, item 1". Anything else as it is. */
export function citedByText(path: string): string {
  const item = /^(key_judgments|alternatives)\[(\d+)\]$/.exec(path);
  if (item) {
    const where = item[1] === "key_judgments" ? "Key judgments" : "Alternatives";
    return `${where}, item ${Number(item[2]) + 1}`;
  }
  const paragraph = /^analysis\[(\d+)\]\.paragraphs\[(\d+)\]$/.exec(path);
  if (paragraph) {
    return `Analysis, section ${Number(paragraph[1]) + 1}, paragraph ${Number(paragraph[2]) + 1}`;
  }
  return path;
}

/** §4.1: a stage the report was delivered without (`metadata.degradations`, R-M11-2), as a
 * sentence, with the engine's error kept for Details. A line in neither form stays as it is. */
export function degradationText(line: string): { text: string; detail: string | null } {
  const match =
    /^(conveyance skipped|audit incomplete) after (\d+) attempts?(?:: ([\s\S]*))?$/.exec(line);
  if (!match) return { text: line, detail: null };
  const attempts = plural(Number(match[2]), "attempt");
  const text =
    match[1] === "conveyance skipped"
      ? `Editing for the reader was skipped after ${attempts}.`
      : `The standards check didn't finish after ${attempts}.`;
  return { text, detail: match[3] ?? null };
}

/** §4.1: a delivered report's status in words: `clean`, or `findings_open` with the rules still
 * open, or `findings_open` only because a stage was skipped. */
export function reportStatusText(status: ReportStatus, open: number): string {
  if (status === "clean") return "Meets the standards";
  return open > 0 ? `${plural(open, "standard")} not met` : "Checked in part";
}
