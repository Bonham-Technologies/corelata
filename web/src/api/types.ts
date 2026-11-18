import type { components } from "./schema";

type S = components["schemas"];

export type SystemInfo = S["SystemInfo"];
export type DoctorReport = S["DoctorReport"];
export type DoctorCheck = S["DoctorCheck"];
export type ProjectView = S["ProjectView"];
export type LatestRun = S["LatestRun"];
export type SourceView = S["SourceView"];
export type SourceKind = S["SourceKind"];
export type RunProgress = S["RunProgress"];
export type RunSummary = S["RunSummary"];
export type RunPage = S["RunPage"];
export type RunState = S["RunState"];
export type ReportStatus = S["ReportStatus"];
export type StageResult = S["StageResult"];
export type Usage = S["Usage"];
export type CreateRun = S["CreateRun"];
export type ReviewAction = S["ReviewAction"];
export type ReviewResult = S["ReviewResult"];
export type ReviewState = S["ReviewState"];
export type ReviewDecision = S["ReviewDecision"];
export type DiscoveryView = S["DiscoveryView"];
export type DiscoveryState = S["DiscoveryState"];
export type CandidateStatement = S["CandidateStatement"];
export type PackSummary = S["PackSummary"];
export type ProfileSummary = S["ProfileSummary"];
export type ResolvedPack = S["ResolvedPack"];
export type Rule = S["Rule"];
export type RunTrace = S["RunTrace"];
export type TraceSummary = S["TraceSummary"];
export type StageLine = S["StageLine"];
export type SourceSummary = S["SourceSummary"];
export type IterationFindings = S["IterationFindings"];
export type DraftStep = S["DraftStep"];
export type PriorReport = S["PriorReport"];
export type DraftChanges = S["DraftChanges"];
export type CallSummary = S["CallSummary"];
export type Finding = S["Finding"];
export type Verdict = S["Verdict"];
export type Severity = S["Severity"];
export type ClaimProvenance = S["ClaimProvenance"];
export type EvidenceUnit = S["EvidenceUnit"];
export type Claim = S["Claim"];
export type Quote = S["Quote"];
export type ClaimKind = S["ClaimKind"];
export type GateVerdict = S["GateVerdict"];
export type ErrorBody = S["ErrorBody"];

export type ReportFormat = "json" | "md" | "html" | "docx";
export type ExportName =
  "trace.json" | "gate.json" | "report.json" | "report.md" | "report.html" | "report.docx";

/** The delivered report as `report.json` serves it (the engine's `Report`; not in the OpenAPI
 * document because the route returns bytes). Only the fields the review screen reads. */
export type ReportJson = {
  title: string;
  claims: Claim[];
  metadata: {
    run_id: string;
    pack_name: string;
    pack_hash: string;
    profile: string | null;
    iteration: number;
    status: ReportStatus;
    open_findings: string[];
    /** Stages the report was delivered without (R-M11-2); absent before M11. */
    degradations?: string[];
  };
};
