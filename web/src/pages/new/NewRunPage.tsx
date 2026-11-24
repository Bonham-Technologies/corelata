import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { isNotFound } from "../../api/client";
import { useProjects, useSources } from "../../api/projects";
import { useEarlierRun, useStartRun } from "../../api/runs";
import { useInfo } from "../../api/system";
import type { SourceView } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { NotFound } from "../../components/NotFound";
import { clearDraft, useDraft } from "../../lib/draft";
import { VALUE_STATEMENT_MAX_LENGTH } from "../../lib/limits";
import { SearchParamsWriterProvider, useSearchParamsWriter } from "../../lib/searchParams";
import { decodeSelection, encodeSelection, SELECTION_PARAM, withAdded } from "../../lib/selection";
import { FROM_PARAM, offeredStatement } from "../../lib/startFrom";
import { ProjectPicker } from "./ProjectPicker";
import { RunList } from "./RunList";
import { RunOptions } from "./RunOptions";
import { SourcesPanel } from "./SourcesPanel";
import { ValueStatement } from "./ValueStatement";

/** The chosen sources' URL parameter before CRL-54: `sources=<id>,<id>` (CRL-40, R-M17-6). It
 * is still read, so old links load; the page writes `pick` (lib/selection) in its place. */
export const SOURCES_PARAM = "sources";

/** M18 spec §5.1 and §5.2: New report without a project, and the project page. The project,
 * the discovery (R-M16-14) and the chosen sources live in the URL, so a reload keeps them; the
 * statement and the options are the project's draft in sessionStorage (CRL-74) until Write the
 * report. The sidebar switches projects: its links name the project alone, so another project
 * drops the discovery and the sources, and shows that project's own draft. A link from an
 * earlier run (`from`, CRL-84) fills the draft and the sources from that run, then leaves the URL.
 * Every write to the URL goes through one writer, so writes that race compose (CRL-62). */
export function NewRunPage() {
  const [params, update] = useSearchParamsWriter();
  const projectId = params.get("project");
  useActiveProject(projectId);
  const projects = useProjects();
  const current = (projects.data ?? []).find((p) => p.id === projectId);
  const sources = useSources(projectId);
  // CRL-130: the project's sources answer 404 when the project does not exist (or was deleted);
  // the page then says so in place of the form, and NotFound names the tab.
  const missing = isNotFound(sources.error, projectId ?? undefined);
  useDocumentTitle(
    projectId === null
      ? "New report – Corelata"
      : current && !missing
        ? `${current.name} – Corelata`
        : null,
  );
  const allIds = useMemo(() => (sources.data ?? []).map((s) => s.id), [sources.data]);
  const selected = useMemo(() => chosenIn(params, allIds), [params, allIds]);
  // Sources uploaded here that the project's list does not show yet: a tick that lands before
  // the refetch reads the URL with them, so it keeps them chosen (CRL-62).
  const pending = useRef(new Set<string>());
  useEffect(() => pending.current.clear(), [projectId]);
  const toggle = useCallback(
    (sourceId: string, on: boolean) => {
      const known = [...allIds, ...[...pending.current].filter((id) => !allIds.includes(id))];
      // replace, as for the discovery: Back does not step through every tick of a checkbox
      update(
        (now) => {
          const next = chosenIn(now, known);
          if (on) next.add(sourceId);
          else next.delete(sourceId);
          now.delete(SOURCES_PARAM); // an old link's list gives way to the short form
          now.set(SELECTION_PARAM, encodeSelection(known, next));
          return now;
        },
        { replace: true },
      );
    },
    [update, allIds],
  );

  const navigate = useNavigate();
  const start = useStartRun();
  // The statement and the options are the project's draft, kept in sessionStorage so a reload
  // or a sign-in redirect does not lose them, and cleared once the run starts (CRL-74).
  const [draft, changeDraft] = useDraft(projectId);
  const { statement, profile } = draft; // profile null: the deployment's default
  const setStatement = useCallback(
    (value: string) => changeDraft((d) => ({ ...d, statement: value })),
    [changeDraft],
  );
  const setProfile = useCallback(
    (value: string | null) => changeDraft((d) => ({ ...d, profile: value })),
    [changeDraft],
  );
  const setMaxIterations = useCallback(
    (value: number | null) => changeDraft((d) => ({ ...d, maxIterations: value })),
    [changeDraft],
  );
  // Revision rounds start from the deployment's pipeline.max_iterations (CRL-67) and follow it
  // until the analyst changes the field. Without the info the server applies its own setting;
  // the field shows the engine's default meanwhile.
  const info = useInfo();
  const chosenIterations = draft.maxIterations;
  const configuredIterations = info.data?.max_iterations ?? null;
  const sentIterations = chosenIterations ?? configuredIterations;
  const maxIterations = sentIterations ?? 2;
  const sourceIds = (sources.data ?? []).filter((s) => selected.has(s.id)).map((s) => s.id);

  // A link from an earlier run fills the form with what that run was asked: its statement (or
  // the one the link offers, the value check's suggested scope), its sources, profile and
  // rounds. It wins over the project's draft; `from` then leaves the URL, so a reload keeps the
  // edits made since, which are the draft by then (CRL-84, CRL-74). Sources deleted since, and
  // ids that are not this project's, are dropped as for any `pick`; sources uploaded here are
  // kept. A run of another project fills nothing; a run that cannot be read leaves the URL too,
  // and its error stays by the statement until another project or link (CRL-108). The options
  // check the profile only once `from` has left, so a stale profile in the draft does not touch
  // the draft before the run replaces it.
  const fromId = params.get(FROM_PARAM);
  const earlier = useEarlierRun(fromId);
  const [failed, setFailed] = useState<{ projectId: string; fromId: string; error: Error } | null>(
    null,
  );
  if (failed !== null && failed.projectId !== projectId) setFailed(null);
  else if (fromId !== null && projectId !== null) {
    const error = earlier.error;
    // `failed`, if any, is this project's here
    if (error && (failed?.fromId !== fromId || failed.error !== error))
      setFailed({ projectId, fromId, error });
    else if (!error && failed !== null && failed.fromId !== fromId) setFailed(null);
  }
  const fromError = failed?.error ?? null;
  const dropFrom =
    earlier.error !== null || (earlier.data && earlier.data.project_id !== projectId);
  useEffect(() => {
    if (fromId === null || !dropFrom) return;
    update(
      (now) => {
        now.delete(FROM_PARAM);
        return now;
      },
      { replace: true },
    );
  }, [fromId, dropFrom, update]);
  const offered = offeredStatement(useLocation().state);
  // The draft as the link found it. What the analyst writes while the run still loads is kept:
  // the run then fills only the sources.
  const [linked, setLinked] = useState({ fromId, draft });
  if (linked.fromId !== fromId) setLinked({ fromId, draft });
  const untouched = linked.draft;
  useEffect(() => {
    const run = earlier.data;
    if (fromId === null || run?.run_id !== fromId || !sources.data) return;
    if (run.project_id !== projectId) return; // ignored; the effect above drops `from`
    const filled = {
      statement: offered ?? run.value_statement,
      profile: run.profile ?? null,
      maxIterations: run.max_iterations,
    };
    changeDraft((now) => (now === untouched ? filled : now));
    update(
      (now) => {
        now.delete(FROM_PARAM);
        now.delete(SOURCES_PARAM);
        // a source uploaded here while the run loaded stays chosen, as for a tick (CRL-62)
        const uploaded = [...pending.current];
        const known = [...allIds, ...uploaded.filter((id) => !allIds.includes(id))];
        now.set(SELECTION_PARAM, encodeSelection(known, new Set([...run.source_ids, ...uploaded])));
        return now;
      },
      { replace: true },
    );
  }, [
    earlier.data,
    fromId,
    projectId,
    sources.data,
    allIds,
    offered,
    untouched,
    changeDraft,
    update,
  ]);

  // Use this statement on a report row: the statement field takes it, and the focus, since it
  // is far above the list.
  const statementBox = useRef<HTMLTextAreaElement>(null);
  const takeStatement = useCallback(
    (value: string) => {
      setStatement(value);
      statementBox.current?.focus();
    },
    [setStatement],
  );
  const canStart =
    Boolean(projectId) &&
    statement.trim().length > 0 &&
    statement.length <= VALUE_STATEMENT_MAX_LENGTH &&
    sourceIds.length > 0 &&
    !start.isPending;

  function startRun() {
    if (!projectId) return;
    start.mutate(
      {
        project_id: projectId,
        source_ids: sourceIds,
        value_statement: statement.trim(),
        profile,
        max_iterations: sentIterations,
        extra_guidance: "",
        kind: "report",
      },
      {
        onSuccess: (run) => {
          clearDraft(projectId);
          navigate(`/runs/${run.run_id}`);
        },
      },
    );
  }

  // choosing a project names it alone: no discovery, no chosen sources (R-M16-14, R-M17-6)
  // A project made here replaces the form that had focus: its heading takes focus next.
  const heading = useRef<HTMLHeadingElement>(null);
  const focusHeading = useRef(false);
  const changeProject = useCallback(
    (id: string, created = false) => {
      focusHeading.current = created;
      update(() => new URLSearchParams(id ? { project: id } : {}));
    },
    [update],
  );
  useEffect(() => {
    if (focusHeading.current && heading.current) {
      focusHeading.current = false;
      heading.current.focus();
    }
  }, [projectId]);
  // A multi-file upload calls this once per file from one click's closure; the writer reads the
  // URL as the last write left it and appends, so no earlier file is lost.
  const added = useCallback(
    (list: SourceView[]) => {
      const ids = list.map((s) => s.id);
      for (const id of ids) pending.current.add(id);
      update(
        (now) => {
          const short = now.get(SELECTION_PARAM);
          const old = now.get(SOURCES_PARAM);
          let value: string;
          if (short !== null) value = withAdded(short, ids);
          else if (old !== null)
            value = withAdded("i", [...old.split(",").filter(Boolean), ...ids]);
          else return null; // every source is selected already, the new ones too
          now.delete(SOURCES_PARAM); // an old link's list gives way to the short form
          now.set(SELECTION_PARAM, value); // `x`: the new ones are chosen already, no change
          return now;
        },
        { replace: true },
      );
    },
    [update],
  );

  if (!projectId) {
    return (
      <article className="new-report">
        <h1>New report</h1>
        <ProjectPicker projectId={null} onChange={changeProject} />
      </article>
    );
  }
  if (missing) {
    return (
      <NotFound heading="Project not found" action="Choose a project">
        This project does not exist, or it was deleted.
      </NotFound>
    );
  }
  return (
    <SearchParamsWriterProvider value={update}>
      <article className="project-page">
        <p className="eyebrow">Project</p>
        <h1 ref={heading} tabIndex={-1} dir="auto">
          {current?.name ?? "Project"}
        </h1>
        <SourcesPanel projectId={projectId} selected={selected} onToggle={toggle} onAdded={added} />
        <ValueStatement
          ref={statementBox}
          key={projectId}
          projectId={projectId}
          sourceIds={sourceIds}
          value={statement}
          onChange={setStatement}
          error={fromError}
        />
        <RunOptions
          key={`options:${projectId}`}
          settled={fromId === null}
          profile={profile}
          onProfile={setProfile}
          maxIterations={maxIterations}
          onMaxIterations={setMaxIterations}
        />
        <div className="row write">
          <button type="button" className="primary" onClick={startRun} disabled={!canStart}>
            {start.isPending ? "Starting…" : "Write the report"}
          </button>
          {sourceIds.length === 0 && sources.data ? (
            <span className="muted">Choose at least one source.</span>
          ) : null}
          {start.error ? <ErrorMessage error={start.error} /> : null}
        </div>
        <RunList key={`runs:${projectId}`} projectId={projectId} onUse={takeStatement} />
      </article>
    </SearchParamsWriterProvider>
  );
}

/** The project's sources `all` that the URL chooses. Without a parameter every source is
 * chosen, new ones too. Ids that are not the project's (removed, or a link from another
 * project) are dropped without a word. */
function chosenIn(params: URLSearchParams, all: readonly string[]): Set<string> {
  const picked = params.get(SELECTION_PARAM);
  if (picked !== null) return decodeSelection(picked, all);
  const listed = params.get(SOURCES_PARAM);
  if (listed === null) return new Set(all);
  const chosen = new Set(listed.split(","));
  return new Set(all.filter((id) => chosen.has(id)));
}
