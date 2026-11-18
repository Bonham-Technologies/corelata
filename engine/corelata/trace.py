"""Read a run's trace and answer what the review screens ask (spec §10.3): what happened when,
what failed in which iteration, where a claim's evidence sits, how a draft changed between
iterations. Pure functions of RunRecord; the CLI calls them now and the API will from M4a."""

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from corelata.ingest.units import ocr_note, ocr_page_count
from corelata.schema import (
    Claim,
    Finding,
    GateVerdict,
    PriorReport,
    Report,
    ReportBody,
    ReportStatus,
    RunRecord,
    RunState,
    Source,
    SourceKind,
    Usage,
    Verdict,
)
from corelata.stages.audit import open_findings


def _empty(items: list) -> bool:
    return not items


class TraceError(ValueError):
    """A run directory or record the trace tools cannot use; the message says why."""


class SourceSummary(BaseModel):
    id: str
    name: str
    kind: SourceKind
    format: str
    sha256: str  # of the uploaded bytes: joins the run to the project's source list (spec §10.3)
    units: int
    digested: bool
    coglossa_run_id: str | None
    ocr_pages: int  # pages whose text OCR recovered from a scan (CRL-95); 0 for none


class StageLine(BaseModel):
    stage: str
    iteration: int
    ok: bool
    duration_ms: int
    error: str | None


class IterationFindings(BaseModel):
    iteration: int
    failed: list[str]  # rule ids with verdict fail, sorted
    open: list[str]  # finding ids that would loop (fail + blocking/major), sorted
    passed: int
    attested: int
    not_applicable: int


class TraceSummary(BaseModel):
    run_id: str
    state: RunState
    status: ReportStatus | None
    error: str | None
    value_statement: str
    pack_name: str
    pack_hash: str
    profile: str | None
    iterations: int
    max_iterations: int
    sources: list[SourceSummary]
    gate: GateVerdict | None
    stages: list[StageLine]
    findings: list[IterationFindings]
    open_findings: list[Finding]
    usage: Usage
    prompt_versions: dict[str, int]
    # CRL-97: the earlier accepted reports the run was given (the Process tab lists them); left
    # out when there are none
    prior_reports: list[PriorReport] = Field(default_factory=list, exclude_if=_empty)


class EvidenceUnit(BaseModel):
    ref: str
    source_id: str
    source_name: str
    locator: str
    text: str


class ClaimProvenance(BaseModel):
    claim: Claim
    evidence: list[EvidenceUnit]
    cited_by: list[str]  # "key_judgments[0]", "analysis[1].paragraphs[2]", "alternatives[0]"


class DraftChanges(BaseModel):
    title_changed: bool
    claims_added: list[str]
    claims_removed: list[str]
    claims_reworded: list[str]
    key_judgments_changed: bool
    sections_changed: list[str]  # headings whose paragraphs differ, or that appear/disappear


class CallSummary(BaseModel):
    """An LLMCallRecord without its request and response bodies (the trace download has them)."""

    role: str
    backend: str
    model: str
    prompt_id: str
    prompt_version: int
    attempt: int
    ok: bool
    latency_ms: int
    tokens_in: int | None
    tokens_out: int | None
    error: str | None


class DraftStep(BaseModel):
    role: str
    iteration: int
    changes: DraftChanges | None  # against the draft before it; None for the first draft


class RunTrace(BaseModel):
    """`GET /api/runs/{id}/trace` (spec §10.1): the summary plus what the Process tab shows
    (spec §10.3) — how each draft changed the one before it, and every model call."""

    summary: TraceSummary
    drafts: list[DraftStep]
    calls: list[CallSummary]


def delivered_open_findings(record: RunRecord) -> list[Finding]:
    """What the appendix lists: the findings `metadata.open_findings` names, which are the last
    completed audit's looping failures (the previous one's when the last audit did not complete,
    R-M11-2, less any engine-check failure the engine no longer finds on the delivered draft,
    CRL-30)."""
    if record.report is None:
        return []
    ids = set(record.report.metadata.open_findings)
    return [f for f in record.findings if f.id in ids]


def load_record(run_dir: Path) -> RunRecord:
    path = run_dir / "trace.json"
    if not path.is_file():
        raise TraceError(f"no trace.json in {run_dir}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise TraceError(f"{path}: trace.json is not valid JSON: {e}") from e
    try:
        return RunRecord.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise TraceError(
            f"{path}: trace.json is not a Corelata run record ({where}: {first['msg']})"
        ) from e


def summarize(record: RunRecord) -> TraceSummary:
    digested = {d.source_id for d in record.digests}
    by_iteration: dict[int, list[Finding]] = {}
    for f in record.findings:
        by_iteration.setdefault(f.iteration, []).append(f)
    findings = [
        IterationFindings(
            iteration=it,
            failed=sorted(f.rule_id for f in fs if f.verdict is Verdict.FAIL),
            open=sorted(f.id for f in open_findings(fs)),
            passed=sum(f.verdict is Verdict.PASS for f in fs),
            attested=sum(f.verdict is Verdict.ATTESTED for f in fs),
            not_applicable=sum(f.verdict is Verdict.NOT_APPLICABLE for f in fs),
        )
        for it, fs in sorted(by_iteration.items())
    ]
    return TraceSummary(
        run_id=record.run_id,
        state=record.state,
        status=record.status,
        error=record.error,
        value_statement=record.value_statement,
        pack_name=record.pack_name,
        pack_hash=record.pack_hash,
        profile=record.profile,
        iterations=record.iterations,
        max_iterations=record.max_iterations,
        sources=[
            SourceSummary(
                id=s.id,
                name=s.name,
                kind=s.kind,
                format=s.format,
                sha256=s.sha256,
                units=len(s.units),
                digested=s.id in digested,
                coglossa_run_id=s.provenance.get("coglossa_run_id"),
                ocr_pages=ocr_page_count(s),
            )
            for s in record.sources
        ],
        gate=record.gate,
        stages=[
            StageLine(
                stage=s.stage,
                iteration=s.iteration,
                ok=s.ok,
                duration_ms=int((s.finished_at - s.started_at).total_seconds() * 1000),
                error=s.error,
            )
            for s in record.stages
        ],
        findings=findings,
        open_findings=delivered_open_findings(record),
        usage=record.usage,
        prompt_versions=record.prompt_versions,
        prior_reports=record.prior_reports,
    )


def claim_provenance(record: RunRecord, claim_id: str) -> ClaimProvenance:
    if record.report is None:
        raise TraceError(f"run {record.run_id} has no report (state {record.state.value})")
    return report_claim_provenance(record.run_id, record.report, record.sources, claim_id)


def report_claim_provenance(
    run_id: str, report: Report, sources: Sequence[Source], claim_id: str
) -> ClaimProvenance:
    """`claim_provenance` from the only parts of the record it reads: the report and the
    sources' units (the API's claim read loads no more, CRL-103)."""
    claim = next((c for c in report.claims if c.id == claim_id), None)
    if claim is None:
        raise TraceError(f"unknown claim id '{claim_id}' in run {run_id}")
    units = {
        f"{s.id}/{u.id}": EvidenceUnit(
            ref=f"{s.id}/{u.id}", source_id=s.id, source_name=s.name, locator=u.locator, text=u.text
        )
        for s in sources
        for u in s.units
    }
    evidence = [units[r] for r in claim.evidence if r in units]
    cited_by = [
        f"key_judgments[{i}]"
        for i, kj in enumerate(report.key_judgments)
        if claim_id in kj.claim_ids
    ]
    for si, section in enumerate(report.analysis):
        for pi, p in enumerate(section.paragraphs):
            if claim_id in p.claim_ids:
                cited_by.append(f"analysis[{si}].paragraphs[{pi}]")
    cited_by += [
        f"alternatives[{i}]" for i, a in enumerate(report.alternatives) if claim_id in a.claim_ids
    ]
    return ClaimProvenance(claim=claim, evidence=evidence, cited_by=cited_by)


def draft_changes(prev: ReportBody, new: ReportBody) -> DraftChanges:
    before = {c.id: c for c in prev.claims}
    after = {c.id: c for c in new.claims}
    prev_sections = {s.heading: [p.model_dump() for p in s.paragraphs] for s in prev.analysis}
    new_sections = {s.heading: [p.model_dump() for p in s.paragraphs] for s in new.analysis}
    return DraftChanges(
        title_changed=prev.title != new.title,
        claims_added=sorted(set(after) - set(before)),
        claims_removed=sorted(set(before) - set(after)),
        claims_reworded=sorted(
            cid for cid in before.keys() & after.keys() if before[cid] != after[cid]
        ),
        key_judgments_changed=[k.model_dump() for k in prev.key_judgments]
        != [k.model_dump() for k in new.key_judgments],
        sections_changed=sorted(
            h
            for h in prev_sections.keys() | new_sections.keys()
            if prev_sections.get(h) != new_sections.get(h)
        ),
    )


def run_trace(record: RunRecord) -> RunTrace:
    steps: list[DraftStep] = []
    prev: ReportBody | None = None
    for draft in record.drafts:
        changes = None if prev is None else draft_changes(prev, draft.report)
        steps.append(DraftStep(role=draft.role, iteration=draft.iteration, changes=changes))
        prev = draft.report
    calls = [
        CallSummary.model_validate(c.model_dump(exclude={"request", "response"}))
        for c in record.llm_calls
    ]
    return RunTrace(summary=summarize(record), drafts=steps, calls=calls)


def format_summary(s: TraceSummary, degradations: Sequence[str] = ()) -> str:
    """`degradations` are the delivered report's (`metadata.degradations`); the summary model
    does not carry them, so the schemas stay as they are."""
    out: list[str] = []
    if s.state is RunState.COMPLETED and s.status is not None:
        out.append(
            f"run {s.run_id}: completed {s.status.value} after {s.iterations} revision(s) "
            f"(max {s.max_iterations})"
        )
    else:
        out.append(f"run {s.run_id}: {s.state.value}" + (f": {s.error}" if s.error else ""))
    out += [f"degraded: {line}" for line in degradations]
    out.append(
        f"pack: {s.pack_name}@{s.pack_hash}" + (f" profile {s.profile}" if s.profile else "")
    )
    out.append(f"statement: {s.value_statement}")
    if s.prior_reports:
        out.append("earlier accepted reports:")
        out += [
            f"  {p.run_id} {p.accepted_at:%Y-%m-%d} {p.title}"
            + (" (cut: over the token budget)" if p.cut else "")
            for p in s.prior_reports
        ]
    out.append("sources:")
    for src in s.sources:
        extra = f", Coglossa run {src.coglossa_run_id}" if src.coglossa_run_id else ""
        extra += ", digested" if src.digested else ""
        extra += f", {ocr_note(src.ocr_pages)}" if src.ocr_pages else ""
        out.append(f"  {src.id} {src.name} ({src.format}, {src.units} units{extra})")
    if s.gate is not None:
        supported = "supported" if s.gate.supported else "not supported"
        out.append(f"gate: {supported}, {s.gate.substance.value}; {' '.join(s.gate.reasons)}")
    out.append("stages:")
    for st in s.stages:
        flag = "ok  " if st.ok else "FAIL"
        err = f"  {st.error}" if st.error else ""
        out.append(f"  {st.stage:<11} it{st.iteration}  {flag} {st.duration_ms:>6} ms{err}")
    if s.findings:
        out.append("findings:")
        for it in s.findings:
            failed = ", ".join(it.failed) if it.failed else "none"
            out.append(
                f"  iteration {it.iteration}: failed {failed}; open {len(it.open)}; "
                f"passed {it.passed}; attested {it.attested}; n/a {it.not_applicable}"
            )
    if s.open_findings:
        out.append("open at delivery:")
        out += [f"  {f.id} ({f.severity}): {f.evidence}" for f in s.open_findings]
    by_role = "; ".join(
        f"{role} {u.get('calls', 0)} call(s), "
        f"{u.get('tokens_in', 0)} in / {u.get('tokens_out', 0)} out"
        for role, u in sorted(s.usage.by_role.items())
    )
    out.append(
        f"usage: {s.usage.calls} calls, {s.usage.tokens_in} in / {s.usage.tokens_out} out tokens"
        + (f"; {by_role}" if by_role else "")
    )
    return "\n".join(out) + "\n"
