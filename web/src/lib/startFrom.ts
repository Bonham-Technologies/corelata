/** A new report that starts from an earlier run (CRL-84): `/new?project=<id>&from=<run id>`
 * fills the form with what that run was asked. The page takes `from` out of the URL once it
 * has filled the form, so a reload keeps the edits made since. */
export const FROM_PARAM = "from";

/** The new-report page, filled from the run `runId` of project `projectId`. */
export function startFromLink(projectId: string, runId: string): string {
  return `/new?project=${projectId}&${FROM_PARAM}=${runId}`;
}

/** What a link to a new report can carry besides `from`, in the history entry rather than the
 * URL, so the text never reaches a server's logs: a statement to use in place of the run's own
 * (the value check's suggested scope). */
export interface StartFromState {
  statement: string;
}

/** The statement a link's history state offers, or null. */
export function offeredStatement(state: unknown): string | null {
  const statement = (state as Partial<StartFromState> | null)?.statement;
  return typeof statement === "string" ? statement : null;
}
