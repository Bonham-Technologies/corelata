import { useResolvedPack } from "../../api/packs";
import { useFindings, useTrace } from "../../api/reports";
import type { Finding, Rule } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { severityText, VERDICT } from "../../lib/words";

export type AuditRow = {
  ruleId: string;
  title: string;
  advisory: boolean;
  latest: Finding;
  history: Finding[]; // by iteration
};

/** One row per rule (spec §10.3 Audit tab): the last iteration's finding, with the history. */
export function auditRows(findings: Finding[], rules: Rule[] | undefined): AuditRow[] {
  const byRule = new Map<string, Finding[]>();
  for (const f of findings) byRule.set(f.rule_id, [...(byRule.get(f.rule_id) ?? []), f]);
  const ruleIndex = new Map((rules ?? []).map((r) => [r.id, r]));
  const order = (id: string) => {
    const i = (rules ?? []).findIndex((r) => r.id === id);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...byRule.entries()]
    .sort(([a], [b]) => order(a) - order(b))
    .map(([ruleId, list]) => {
      const history = [...list].sort((a, b) => a.iteration - b.iteration);
      const rule = ruleIndex.get(ruleId);
      // A rule the pack marks advisory is checked when the run read earlier reports (its
      // `with_prior_reports`, CRL-97): a met or not-met verdict puts it with the checked rules.
      const checked = history.some((f) => f.verdict === "pass" || f.verdict === "fail");
      return {
        ruleId,
        title: rule?.title ?? ruleId,
        advisory: rule?.checkability === "advisory" && !checked,
        latest: history.at(-1)!,
        history,
      };
    });
}

/** The severities whose failures keep a report open: the engine's LOOPING set
 * (engine/corelata/stages/audit.py), so "not met" here is what `metadata.open_findings` holds. */
const OPENING = new Set(["blocking", "major"]);

export type StandardsGroups = {
  notMet: AuditRow[];
  minor: AuditRow[];
  met: AuditRow[];
  advisory: AuditRow[];
};

/** R-M18-27: one meaning of "not met". A rule is not met when its latest verdict is a fail at
 * blocking or major severity; a latest fail at minor severity is a minor issue, which leaves the
 * report clean, as the engine has it. */
export function standardsGroups(rows: AuditRow[]): StandardsGroups {
  const checked = rows.filter((r) => !r.advisory);
  const failing = checked.filter((r) => r.latest.verdict === "fail");
  return {
    notMet: failing.filter((r) => OPENING.has(r.latest.severity)),
    minor: failing.filter((r) => !OPENING.has(r.latest.severity)),
    met: checked.filter((r) => r.latest.verdict !== "fail"),
    advisory: rows.filter((r) => r.advisory),
  };
}

/** How many minor issues a report has: its rules whose latest verdict is a minor fail. It needs no
 * pack: a rule with a fail is never grouped as advisory (`auditRows`). */
export function minorIssueCount(findings: Finding[]): number {
  return standardsGroups(auditRows(findings, undefined)).minor.length;
}

function verdictText(finding: Finding): string {
  const v = VERDICT[finding.verdict];
  return `${v.symbol} ${v.text}`;
}

/** M18 spec §5.4: one block per rule, not a table. */
function RuleGroup({ label, rows }: { label: string; rows: AuditRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="rule-group">
      <h3>{label}</h3>
      <ul aria-label={label} className="rules">
        {rows.map((r) => (
          <li key={r.ruleId} className="rule">
            <p className="rule-title">
              <strong dir="auto">{r.title}</strong>{" "}
              <span className="muted" dir="auto">
                {r.ruleId}
              </span>
            </p>
            <p className="row">
              <span className={`verdict verdict-${r.latest.verdict}`}>{verdictText(r.latest)}</span>
              <span className="muted">{severityText(r.latest.severity)}</span>
            </p>
            <details>
              <summary>Why</summary>
              <p dir="auto">{r.latest.evidence}</p>
              {r.latest.recommendation ? (
                <p className="muted" dir="auto">
                  {r.latest.recommendation}
                </p>
              ) : null}
            </details>
            {r.history.length > 1 ? (
              <p className="muted" role="group" aria-label="History">
                {r.history.map(verdictText).join(" → ")}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The Standards tab (tab id `audit`): Not met first, then Minor issues (R-M18-27), then Met and
 * not applicable, then the advisory rules (attested). */
export function AuditTab({ runId, degradations = [] }: { runId: string; degradations?: string[] }) {
  const findings = useFindings(runId);
  const trace = useTrace(runId);
  const summary = trace.data?.summary;
  const pack = useResolvedPack(summary?.pack_name ?? null, summary?.profile ?? null);
  const loadingTitles = trace.isPending || (pack.isPending && pack.fetchStatus === "fetching");
  if (findings.isPending) return <Loading what="Loading the standards check" />;
  if (findings.error) return <ErrorMessage error={findings.error} />;
  const rows = auditRows(findings.data ?? [], pack.data?.rules);
  // one meaning of "not met" for the notice and the groups (R-M18-27)
  const groups = standardsGroups(rows);
  // R-M11-2: "audit incomplete after N attempts: <reason>"; the rows shown are the previous check's
  const incomplete = degradations.find((d) => d.startsWith("audit incomplete"));
  const colon = incomplete?.indexOf(": ") ?? -1;
  const reason =
    incomplete !== undefined && colon !== -1 ? incomplete.slice(colon + 2) : incomplete;
  const metNotice =
    groups.minor.length > 0
      ? "Every blocking and major standard that could be checked was met."
      : "Every standard that could be checked was met.";
  return (
    <div className="audit">
      {pack.error ? (
        <p className="muted">
          Rule titles are unavailable: <span data-raw-error>{pack.error.message}</span>
        </p>
      ) : null}
      {incomplete ? (
        <p className="notice" dir="auto">
          The standards check didn&apos;t finish: <span data-raw-error>{reason}</span>
        </p>
      ) : null}
      {rows.length === 0 && !incomplete ? (
        <p className="muted">No standards results were recorded.</p>
      ) : null}
      {rows.length > 0 && groups.notMet.length === 0 && !incomplete ? (
        <p className="notice">{metNotice}</p>
      ) : null}
      {loadingTitles ? (
        <Loading what="Loading rule titles" />
      ) : (
        <>
          <RuleGroup label="Not met" rows={groups.notMet} />
          <RuleGroup label="Minor issues" rows={groups.minor} />
          <RuleGroup label="Met and not applicable" rows={groups.met} />
          <RuleGroup label="Advisory" rows={groups.advisory} />
        </>
      )}
    </div>
  );
}
