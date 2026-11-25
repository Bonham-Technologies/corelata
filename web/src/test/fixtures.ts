import type {
  CandidateStatement,
  ClaimProvenance,
  DoctorReport,
  DiscoveryView,
  Finding,
  PackSummary,
  ProjectView,
  ReportJson,
  ResolvedPack,
  RunPage,
  RunProgress,
  RunSummary,
  RunTrace,
  SourceView,
  SystemInfo,
} from "../api/types";

export const info: SystemInfo = {
  version: "0.1.0",
  auth_mode: "none",
  user: null,
  coglossa: false,
  max_upload_mb: 200,
  default_pack: "icd203-base",
  default_profile: null,
  max_iterations: 2,
};

export const project: ProjectView = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Black Sea",
  created_at: "2026-10-13T10:00:00Z",
  last_activity_at: "2026-10-13T10:00:00Z",
  reports_writing: 0,
  reports_to_review: 0,
  latest_run: null,
};

export const source: SourceView = {
  id: "22222222-2222-2222-2222-222222222222",
  project_id: project.id,
  kind: "file",
  name: "port.txt",
  format: "txt",
  sha256: "a".repeat(64),
  provenance: {},
  created_at: "2026-10-13T10:01:00Z",
  already_in_project: false,
};

export const RUN_ID = "33333333-3333-3333-3333-333333333333";

export function runProgress(overrides: Partial<RunProgress> = {}): RunProgress {
  return {
    run_id: RUN_ID,
    project_id: project.id,
    parent_run_id: null,
    kind: "report",
    report_source_id: null,
    state: "created",
    status: null,
    value_statement: "Varna port capacity expansion matters to shippers",
    extra_guidance: "",
    profile: null,
    source_ids: [source.id],
    iteration: 0,
    max_iterations: 2,
    stages: [],
    usage: null,
    cancel_requested: false,
    worker_gone: false,
    attempts: 0,
    error: null,
    export_error: null,
    review: null,
    created_at: "2026-10-13T10:02:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

/** The report a return revised (CRL-102): completed, and returned with `RETURN_NOTE`, which made
 * the run `RUN_ID` (a revised report has it as its `parent_run_id`). */
export const PARENT_RUN_ID = "33333333-3333-3333-3333-333333333330";
export const RETURN_NOTE = "Add the 2027 date to the title.";

export function returnedParent(overrides: Partial<RunProgress> = {}): RunProgress {
  return runProgress({
    run_id: PARENT_RUN_ID,
    state: "completed",
    status: "clean",
    review: {
      decision: "returned",
      at: "2026-10-13T10:06:00Z",
      actor: null,
      note: RETURN_NOTE,
      child_run_id: RUN_ID,
      child_state: null,
      child_error: null,
    },
    ...overrides,
  });
}

export const runSummary: RunSummary = {
  run_id: RUN_ID,
  project_id: project.id,
  parent_run_id: null,
  kind: "report",
  state: "completed",
  status: "clean",
  value_statement: "Varna port capacity expansion matters to shippers",
  profile: null,
  iteration: 0,
  max_iterations: 2,
  created_at: "2026-10-13T10:02:00Z",
  finished_at: "2026-10-13T10:05:00Z",
};

/** `GET /api/runs` for a project without runs: one page, nothing after it (R-M14-1). */
export const noRuns: RunPage = { runs: [], next_before: null };

export const sources: SourceView[] = [
  source,
  {
    ...source,
    id: "22222222-2222-2222-2222-222222222223",
    kind: "coglossa_export",
    name: "letter.coglossa.json",
    format: "coglossa",
    provenance: { coglossa_run_id: "run-42" },
  },
];

export const DISCOVERY_ID = "44444444-4444-4444-4444-444444444444";

/** The server's default work limit, `worker.discovery_deadline_s` (R-M17-1), counted from the
 * worker's claim. */
export const DEADLINE_MS = 10 * 60_000;
/** The server's default start limit, `worker.discovery_start_deadline_s` (R-M17-26), counted
 * from `created_at` while no worker has claimed the discovery. */
export const START_DEADLINE_MS = 60 * 60_000;

/** `created_at` plus `ms`: the server's `deadline_at` for a discovery `ms` before its limit, by
 * `created_at` (R-M17-27). */
export function deadlineFor(createdAt: string, ms = DEADLINE_MS): string {
  return new Date(Date.parse(createdAt) + ms).toISOString();
}

export function discoveryView(overrides: Partial<DiscoveryView> = {}): DiscoveryView {
  // just created, by the clock the page reads its age with (no `Date` header in tests): a
  // fixed past date would be past the 10-minute ceiling (R-M16-2)
  const createdAt = overrides.created_at ?? new Date().toISOString();
  return {
    discovery_id: DISCOVERY_ID,
    project_id: project.id,
    state: "created",
    audience_hint: "",
    source_ids: [source.id],
    candidates: [],
    usage: null,
    error: null,
    created_at: createdAt,
    deadline_at: deadlineFor(createdAt),
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

/** A `created_at` that many minutes ago, by the test's clock. */
export function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

export const candidates: CandidateStatement[] = [
  {
    text: "Varna port capacity expansion matters to shippers",
    audience: "shipping line planners",
    evidence: [`${source.id}/u1`, `${source.id}/u2`],
    confidence_note: "Two units state the expansion directly.",
  },
  {
    text: "Grain exports through Varna will grow in 2027",
    audience: "commodity traders",
    evidence: [`${source.id}/u2`],
    confidence_note: "One unit; the date is firm.",
  },
];

export const packs: PackSummary[] = [
  {
    name: "icd203-base",
    version: "1.0",
    extends: null,
    description: "ICD 203 analytic standards",
    builtin: true,
    profiles: [
      { name: "team-east", draft: false, tone: "brisk" },
      { name: "draft-west", draft: true, tone: "" },
    ],
    error: null,
  },
];

export const resolvedPack: ResolvedPack = {
  name: "icd203-base",
  version: "1.0",
  profile: null,
  rules: [
    {
      id: "icd203.tc.8",
      title: "Sourcing is clear",
      text: "Every claim cites its evidence.",
      severity: "blocking",
      checkability: "verifiable",
      route_to: "writer",
      applies_to: [],
      evidence_required: "Cite the unit id for every claim.",
      source: "ICD 203 §D.8",
    },
    {
      id: "icd203.tc.7",
      title: "Consistent with prior analysis",
      text: "Changes from earlier judgments are explained.",
      severity: "minor",
      checkability: "advisory",
      route_to: "writer",
      applies_to: [],
      evidence_required: "",
      source: "ICD 203 §D.7",
    },
  ],
  template: {
    section_order: ["key_judgments", "analysis"],
    key_judgments: { min: 1, max: 5 },
    analysis_max_words: 800,
    gaps_required: true,
    alternatives_required_unless_all_high: true,
  },
  lexicon: {
    likelihood: [],
    confidence_definitions: {},
    handling_markings: [],
    source_descriptors: [],
  },
  tone: "",
  format: { docx_reference: null, heading_style: "plain" },
};

export const findings: Finding[] = [
  {
    rule_id: "icd203.tc.8",
    verdict: "fail",
    severity: "blocking",
    route_to: "writer",
    evidence: "Claim c2 has no evidence.",
    cited_units: [],
    claim_ids: ["c2"],
    recommendation: "Cite a unit or drop the claim.",
    iteration: 0,
  },
  {
    rule_id: "icd203.tc.8",
    verdict: "pass",
    severity: "blocking",
    route_to: "writer",
    evidence: "Every claim cites a unit.",
    cited_units: [],
    claim_ids: [],
    recommendation: "",
    iteration: 1,
  },
  {
    rule_id: "icd203.tc.7",
    verdict: "attested",
    severity: "minor",
    route_to: "writer",
    evidence: "No prior analysis available.",
    cited_units: [],
    claim_ids: [],
    recommendation: "",
    iteration: 1,
  },
];

export const runTrace: RunTrace = {
  summary: {
    run_id: RUN_ID,
    state: "completed",
    status: "clean",
    error: null,
    value_statement: runSummary.value_statement,
    pack_name: "icd203-base",
    pack_hash: "b".repeat(16),
    profile: null,
    iterations: 1,
    max_iterations: 2,
    sources: [
      {
        id: "src1",
        name: "port.txt",
        kind: "file",
        format: "txt",
        sha256: "a".repeat(64),
        units: 3,
        digested: false,
        coglossa_run_id: null,
        ocr_pages: 0,
        hidden_units: 0,
        suspect_units: 0,
      },
      {
        id: "src2",
        name: "letter.coglossa.json",
        kind: "coglossa_export",
        format: "coglossa",
        sha256: "c".repeat(64),
        units: 2,
        digested: true,
        coglossa_run_id: "run-42",
        reliability_tier: "B",
        ocr_pages: 0,
        hidden_units: 0,
        suspect_units: 0,
      },
    ],
    gate: {
      supported: true,
      substance: "sufficient",
      reasons: ["Two units support it."],
      evidence: ["src1/u1"],
      suggested_scope: "",
    },
    stages: [
      { stage: "ingesting", iteration: 0, ok: true, duration_ms: 120, error: null },
      { stage: "gating", iteration: 0, ok: true, duration_ms: 2300, error: null },
      { stage: "drafting", iteration: 0, ok: true, duration_ms: 5400, error: null },
      { stage: "conveying", iteration: 0, ok: true, duration_ms: 3100, error: null },
      { stage: "auditing", iteration: 0, ok: true, duration_ms: 2800, error: null },
      { stage: "drafting", iteration: 1, ok: true, duration_ms: 5100, error: null },
      { stage: "conveying", iteration: 1, ok: true, duration_ms: 2900, error: null },
      { stage: "auditing", iteration: 1, ok: true, duration_ms: 2600, error: null },
      { stage: "rendering", iteration: 1, ok: true, duration_ms: 400, error: null },
    ],
    findings: [
      {
        iteration: 0,
        failed: ["icd203.tc.8"],
        open: ["icd203.tc.8@0"],
        passed: 10,
        attested: 1,
        not_applicable: 2,
      },
      { iteration: 1, failed: [], open: [], passed: 11, attested: 1, not_applicable: 2 },
    ],
    open_findings: [],
    usage: {
      calls: 8,
      tokens_in: 12_400,
      tokens_out: 3_900,
      by_role: {
        gate: { calls: 1, tokens_in: 1200, tokens_out: 200 },
        writer: { calls: 2, tokens_in: 6000, tokens_out: 2000 },
        conveyor: { calls: 2, tokens_in: 3000, tokens_out: 1200 },
        auditor: { calls: 3, tokens_in: 2200, tokens_out: 500 },
      },
    },
    prompt_versions: { gate: 1, writer: 1, conveyor: 1, auditor: 1 },
  },
  drafts: [
    { role: "writer", iteration: 0, changes: null },
    {
      role: "conveyor",
      iteration: 0,
      changes: {
        title_changed: true,
        claims_added: [],
        claims_removed: [],
        claims_reworded: [],
        key_judgments_changed: false,
        sections_changed: [],
      },
    },
    {
      role: "writer",
      iteration: 1,
      changes: {
        title_changed: false,
        claims_added: [],
        claims_removed: ["c2"],
        claims_reworded: ["c1"],
        key_judgments_changed: true,
        sections_changed: ["Analysis"],
      },
    },
    {
      role: "conveyor",
      iteration: 1,
      changes: {
        title_changed: false,
        claims_added: [],
        claims_removed: [],
        claims_reworded: [],
        key_judgments_changed: false,
        sections_changed: [],
      },
    },
  ],
  calls: [
    {
      role: "gate",
      backend: "local",
      model: "fake-model",
      prompt_id: "gate",
      prompt_version: 1,
      attempt: 1,
      ok: true,
      latency_ms: 2300,
      tokens_in: 1200,
      tokens_out: 200,
      error: null,
    },
    {
      role: "writer",
      backend: "local",
      model: "fake-model",
      prompt_id: "writer",
      prompt_version: 1,
      attempt: 1,
      ok: true,
      latency_ms: 5400,
      tokens_in: 3000,
      tokens_out: 1000,
      error: null,
    },
  ],
};

export const reportJson: ReportJson = {
  title: "Varna Port Expansion: Implications for Shippers",
  sources: [
    {
      source_id: "src1",
      descriptor: "official government publication",
      reliability_note: "The authority's own figures.",
      origin: "Varna Port Authority",
      access: "direct",
    },
    { source_id: "src2", descriptor: "translated document", reliability_note: "" },
  ],
  claims: [
    {
      id: "c1",
      text: "Varna will add a second grain terminal in 2027.",
      kind: "fact",
      likelihood_term: null,
      evidence: ["src1/u1"],
    },
    {
      id: "c3",
      text: "Waiting times will likely fall by a third.",
      kind: "judgment",
      likelihood_term: "likely",
      evidence: ["src1/u2", "src2/u1"],
      // CRL-93: the second quote is one the browser cannot find (the engine matched it fuzzily)
      quotes: [
        { ref: "src1/u2", text: "\u201cwaiting times at  Varna to fall\u201d" },
        { ref: "src2/u1", text: "a new grain terminal" },
      ],
    },
  ],
  metadata: {
    run_id: RUN_ID,
    pack_name: "icd203-base",
    pack_hash: "b".repeat(16),
    profile: null,
    iteration: 1,
    status: "clean",
    open_findings: [],
  },
};

/** The original's report, titled apart from the revised one's (CRL-102). */
export const parentReportJson: ReportJson = {
  ...reportJson,
  title: "Varna Port Expansion: First Draft",
  metadata: { ...reportJson.metadata, run_id: PARENT_RUN_ID },
};

/** What a run's report carries when its last audit failed twice (R-M11-2). */
export const AUDIT_INCOMPLETE =
  "audit incomplete after 2 attempts: auditor: invalid output after repair: " +
  "findings.icd203.as.1: Field required";

export const degradedReportJson: ReportJson = {
  ...reportJson,
  metadata: {
    ...reportJson.metadata,
    status: "findings_open",
    degradations: [AUDIT_INCOMPLETE],
  },
};

export const claimProvenance: ClaimProvenance = {
  claim: reportJson.claims[1]!,
  evidence: [
    {
      ref: "src1/u2",
      source_id: "src1",
      source_name: "port.txt",
      locator: "para:2",
      text: "Shippers expect waiting times at Varna to fall by a third.",
    },
    {
      ref: "src2/u1",
      source_id: "src2",
      source_name: "letter.coglossa.json",
      locator: "coglossa:run-42/span:p1",
      text: "The port of Varna will add a second grain terminal in 2027.",
    },
  ],
  cited_by: ["key_judgments[0]", "analysis[0].paragraphs[1]"],
};

export const reportHtml = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>${reportJson.title}</title>
<style>body.corelata-report { font-family: Georgia, serif; } h1 { font-size: 1.6rem; }</style></head>
<body class="corelata-report"><article><h1>${reportJson.title}</h1>
<section><h2>Key judgments</h2><ul class="key-judgments">
<li data-claim-ids="c1 c3">Varna will add a second grain terminal in 2027; waiting times will likely fall.<sup class="claim-ids">c1, c3</sup></li>
</ul></section>
<section><h2>Analysis</h2><p data-claim-ids="c1">The terminal doubles grain handling.<sup class="claim-ids">c1</sup></p>
<p data-claim-ids="">A paragraph with no claim.</p></section>
</article></body></html>`;

/** `GET /api/system/doctor?probe=false` on an install with one note (M18 spec §5.6). */
export const doctorReport: DoctorReport = {
  ok: true,
  checks: [
    { name: "config", status: "pass", message: "/etc/corelata/corelata.yaml is valid", fix: "" },
    {
      name: "backend local",
      status: "warn",
      message: "skipped: probe=false",
      fix: "run a full check to send a test completion",
    },
    { name: "database", status: "pass", message: "postgresql://corelata@db at 0006", fix: "" },
  ],
};
