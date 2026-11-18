import { useEffect, useState } from "react";

/** What the analyst has written on a project page before Write the report (CRL-74): the value
 * statement and the options. `profile` null is the deployment's default profile, and
 * `maxIterations` null follows the deployment's configured rounds (CRL-67). */
export interface Draft {
  statement: string;
  profile: string | null;
  maxIterations: number | null;
}

export const EMPTY_DRAFT: Draft = { statement: "", profile: null, maxIterations: null };

const DRAFT_PREFIX = "corelata.draft.";

/** The sessionStorage key of a project's draft. Per tab and per project: a draft never shows in
 * another project, and a reload or a sign-in redirect in the same tab finds it again. */
export function draftKey(projectId: string): string {
  return `${DRAFT_PREFIX}${projectId}`;
}

/** The project's saved draft, or an empty one. A value that is not a draft (written by another
 * version, or by hand) and storage that cannot be read (blocked, a private window) read as
 * empty. */
export function loadDraft(projectId: string): Draft {
  try {
    const raw = sessionStorage.getItem(draftKey(projectId));
    return raw === null ? EMPTY_DRAFT : asDraft(JSON.parse(raw));
  } catch {
    return EMPTY_DRAFT;
  }
}

/** Saves the draft, or removes it when nothing is written. Storage errors (full, blocked) are
 * ignored: the draft stays on the page, it just will not survive a reload. */
export function saveDraft(projectId: string, draft: Draft): void {
  try {
    if (isEmpty(draft)) sessionStorage.removeItem(draftKey(projectId));
    else sessionStorage.setItem(draftKey(projectId), JSON.stringify(draft));
  } catch {
    // ignored, as above
  }
}

export function clearDraft(projectId: string): void {
  try {
    sessionStorage.removeItem(draftKey(projectId));
  } catch {
    // ignored, as above
  }
}

/** Removes every project's draft: on sign-out, so the next person to sign in on this tab does
 * not see what the last one wrote. Storage errors are ignored. */
export function clearAllDrafts(): void {
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, i) => sessionStorage.key(i));
    for (const key of keys) {
      if (key?.startsWith(DRAFT_PREFIX)) sessionStorage.removeItem(key);
    }
  } catch {
    // ignored, as above
  }
}

/** The draft of the project the page shows, kept in sessionStorage as it changes. Another
 * project reads its own draft in the same render, so the old project's text never shows in it,
 * not even for one frame. */
export function useDraft(
  projectId: string | null,
): [Draft, (change: (draft: Draft) => Draft) => void] {
  const [held, setHeld] = useState(() => ({ projectId, draft: read(projectId) }));
  let current = held;
  if (held.projectId !== projectId) {
    current = { projectId, draft: read(projectId) };
    setHeld(current);
  }
  useEffect(() => {
    if (held.projectId !== null) saveDraft(held.projectId, held.draft);
  }, [held]);
  const [update] = useState(
    () => (change: (draft: Draft) => Draft) =>
      setHeld((prev) => ({ projectId: prev.projectId, draft: change(prev.draft) })),
  );
  return [current.draft, update];
}

function read(projectId: string | null): Draft {
  return projectId === null ? EMPTY_DRAFT : loadDraft(projectId);
}

function isEmpty(draft: Draft): boolean {
  return draft.statement === "" && draft.profile === null && draft.maxIterations === null;
}

function asDraft(value: unknown): Draft {
  if (typeof value !== "object" || value === null) return EMPTY_DRAFT;
  const { statement, profile, maxIterations } = value as Record<string, unknown>;
  return {
    statement: typeof statement === "string" ? statement : "",
    profile: typeof profile === "string" ? profile : null,
    maxIterations:
      typeof maxIterations === "number" && Number.isInteger(maxIterations) && maxIterations >= 0
        ? Math.min(10, maxIterations)
        : null,
  };
}
