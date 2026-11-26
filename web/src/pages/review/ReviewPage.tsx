import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { isNotFound } from "../../api/client";
import { liveUpdatesAvailable, useRunEvents } from "../../api/events";
import { useProjects } from "../../api/projects";
import { useFindings, useReportHtml, useReportJson } from "../../api/reports";
import { rerunPending, runKeys, useRun } from "../../api/runs";
import type { RunProgress } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { Loading } from "../../components/Loading";
import { ReportNotFound } from "../../components/NotFound";
import { RevisionOf } from "../../components/RevisionOf";
import { StatementShown } from "../../components/StatementShown";
import { StatusText } from "../../components/StatusText";
import { Tabs } from "../../components/Tabs";
import { reportStatus } from "../../lib/status";
import { AuditTab, minorIssueCount } from "./AuditTab";
import { ProcessTab } from "./ProcessTab";
import { ProvenanceTab } from "./ProvenanceTab";
import { ReportFrame } from "./ReportFrame";
import { ReviewActions } from "./ReviewActions";
import { ReviewBanner } from "./ReviewBanner";
import { SourcesTab } from "./SourcesTab";

/** The tab ids stay those of M4b (they are in links); the labels are the reader's (§5.4). */
const TABS = [
  { id: "provenance", label: "Claims" },
  { id: "audit", label: "Standards" },
  { id: "process", label: "Process" },
  { id: "sources", label: "Sources" },
];
/** A checked report (CRL-94) was not written here, so it has no writing timeline to show. */
const CHECK_TABS = TABS.filter((t) => t.id !== "process");

/** The rerun of a return whose event stream the page follows instead of polling the run (CRL-77):
 * none while no rerun is being written or it has no id yet, without EventSource, and once its
 * stream has ended or failed (`unfollowed`), so the run is polled again if it still says pending. */
function rerunToFollow(run: RunProgress | undefined, unfollowed: string | null): string | null {
  const review = run?.review;
  const rerun = review && rerunPending(review) ? review.child_run_id : null;
  return rerun && rerun !== unfollowed && liveUpdatesAvailable() ? rerun : null;
}

/** M18 spec §5.4. The selected claim and the open tab live in the URL. */
export function ReviewPage() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const claim = params.get("claim");
  const queryClient = useQueryClient();
  const [unfollowed, setUnfollowed] = useState<string | null>(null);
  const run = useRun(runId, (progress) => rerunToFollow(progress, unfollowed) !== null);
  // While a return's rerun is being written, its stream says when it ends; the run is read once
  // then, since its review changes only at that end (CRL-77).
  const rerun = rerunToFollow(run.data, unfollowed);
  const onRerunFailed = useCallback(() => setUnfollowed(rerun), [rerun]);
  const onRerunEnded = useCallback(() => {
    setUnfollowed(rerun);
    void queryClient.invalidateQueries({ queryKey: runKeys.one(runId), exact: true });
  }, [rerun, runId, queryClient]);
  useRunEvents(rerun ?? "", rerun !== null, onRerunFailed, onRerunEnded);
  useActiveProject(run.data?.project_id ?? null);
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === run.data?.project_id);
  const completed = run.data?.state === "completed";
  const html = useReportHtml(runId, completed);
  const json = useReportJson(runId, completed);
  const missing = isNotFound(run.error, runId); // CRL-130: NotFound names the tab
  useDocumentTitle(json.data && !missing ? `${json.data.title} – Corelata` : null);
  const status = json.data?.metadata.status ?? run.data?.status;
  // R-M18-27: a clean report may still have minor issues; the banner names how many. The
  // Standards tab reads the same findings, so the query is shared.
  const findings = useFindings(runId, completed && status === "clean");
  const minor = findings.data ? minorIssueCount(findings.data) : 0;

  // After Accept the button disables; focus goes to the banner that states the decision.
  const banner = useRef<HTMLElement>(null);

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  }

  if (run.isPending) return <Loading what="Loading the report" />;
  if (missing) return <ReportNotFound />;
  if (run.error) return <ErrorMessage error={run.error} />;
  if (!completed) {
    return (
      <section aria-label="No report">
        <p>This report has not been written yet.</p>
        <Link to={`/runs/${runId}`}>See its progress</Link>
      </section>
    );
  }
  const checked = run.data?.kind === "check";
  const tabs = checked ? CHECK_TABS : TABS;
  const tab = tabs.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "provenance";
  const open = json.data?.metadata.open_findings.length ?? 0;
  const degradations = json.data?.metadata.degradations ?? [];
  const review = run.data?.review ?? null;
  return (
    <article className="review">
      <header className="review-header">
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to={`/new?project=${run.data!.project_id}`}>{project?.name ?? "Project"}</Link>
        </nav>
        <div className="row between">
          <div className="row">
            <h1 dir="auto">{json.data?.title ?? "Report"}</h1>
            {status ? (
              <span className="pill">
                <StatusText status={reportStatus(status, open)} />
              </span>
            ) : null}
          </div>
          <ReviewActions
            runId={runId}
            review={review}
            checked={checked}
            onAccepted={() => banner.current?.focus()}
          />
        </div>
        {/* a revised report names its original and the note that asked for it (CRL-102) */}
        {run.data!.parent_run_id ? (
          <RevisionOf runId={runId} parentRunId={run.data!.parent_run_id} />
        ) : null}
        {checked ? (
          <p className="muted">
            A finished report written outside Corelata, checked against the standards as it was
            uploaded. Nothing in it was rewritten.
          </p>
        ) : null}
        {/* what was asked for, to check the report against (CRL-101) */}
        <StatementShown statement={run.data!.value_statement} />
        {json.error ? <ErrorMessage error={json.error} /> : null}
      </header>
      <ReviewBanner
        review={review}
        open={open}
        minor={minor}
        degradations={degradations}
        onShowStandards={() => update({ tab: "audit" })}
        bannerRef={banner}
      />
      <div className="review-body">
        <section aria-label="Report" className="report-pane">
          {html.isPending ? <Loading what="Preparing the report" /> : null}
          {html.error ? <ErrorMessage error={html.error} /> : null}
          {html.data ? (
            <ReportFrame
              html={html.data}
              selectedClaim={claim}
              onSelectClaim={(id) => update({ claim: id, tab: "provenance" })}
            />
          ) : null}
        </section>
        <aside className="side-pane" aria-label="Review details">
          <Tabs
            label="Review details"
            tabs={tabs}
            active={tab}
            onChange={(id) => update({ tab: id })}
          >
            {(active) => {
              switch (active) {
                case "audit":
                  return <AuditTab runId={runId} degradations={degradations} />;
                case "process":
                  return <ProcessTab runId={runId} />;
                case "sources":
                  return <SourcesTab runId={runId} />;
                default:
                  return (
                    <ProvenanceTab
                      runId={runId}
                      reviewed={!checked}
                      selectedClaim={claim}
                      onSelectClaim={(id) => update({ claim: id })}
                    />
                  );
              }
            }}
          </Tabs>
        </aside>
      </div>
    </article>
  );
}
