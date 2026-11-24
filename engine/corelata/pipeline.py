"""The run: gate → writer → conveyor → auditor with one bounded loop (spec §7). A gate or writer
failure ends the run in `failed` with the error recorded; a conveyor or auditor failure is
recorded as a degradation and the report is still delivered (R-M11-2). Nothing raises."""

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from corelata import __version__
from corelata.config import CorelataConfig, config_hash
from corelata.ingest.units import UnitIndex, model_view
from corelata.llm.agent import AGENT_FAILURES, AgentRunner, CallLog
from corelata.llm.types import OVERSIZE_ERRORS, Backend
from corelata.prompts.check import check_prompt_ids, run_prompt_ids
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    DiscoveryResult,
    DraftRecord,
    Finding,
    PriorReport,
    PriorReportRef,
    Report,
    ReportBody,
    ReportMetadata,
    ReportStatus,
    RunKind,
    RunRecord,
    RunState,
    Source,
    StageResult,
    Substance,
)
from corelata.stages.audit import (
    AuditOutcome,
    decide_next,
    engine_only_findings,
    merge_engine_findings,
    open_findings,
    run_auditor,
)
from corelata.stages.context import StageContext, StageError
from corelata.stages.convey import run_conveyor
from corelata.stages.digest import run_digests, writer_overflow
from corelata.stages.gate import run_discovery, run_gate
from corelata.stages.prior import select_prior_reports
from corelata.stages.structure import REPORT_ID, run_structurer
from corelata.stages.write import run_writer
from corelata.standards.loader import load_pack, pack_hash
from corelata.standards.schema import ResolvedPack

# The longest degradation line the report carries (R-M11-7).
DEGRADATION_CHARS = 200
# The degradation line for an audit the run was delivered without; `scenarios` reads it.
AUDIT_INCOMPLETE = "audit incomplete"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunOptions:
    value_statement: str
    profile: str | None = None
    max_iterations: int | None = None
    extra_guidance: str = ""
    run_id: str | None = None
    parent_run_id: str | None = None
    created_at: datetime | None = None  # when the run was created, if before this execution
    # CRL-97: the project's newest accepted reports, newest first, as the host found them (the
    # worker reads them for a queued run); None when the host has no project memory (`corelata
    # run`, the bench) or `pipeline.prior_judgments.max_reports` is 0.
    prior_reports: list[PriorReport] | None = None
    # CRL-94: the finished report a check run audits (its source id `report`); None for a run
    # that writes its own report.
    checked_report: Source | None = None


class RunObserver(Protocol):
    """What a host (the worker) learns while a run executes, and the one question the pipeline
    asks it (spec §7.2 `cancelled`, §10.1 cancel). Hooks run between model calls; they must not
    raise for the run to stay unattended."""

    async def state_changed(self, record: RunRecord) -> None: ...

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None: ...

    async def cancel_requested(self) -> bool: ...


class NullObserver:
    async def state_changed(self, record: RunRecord) -> None:
        return None

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None:
        return None

    async def cancel_requested(self) -> bool:
        return False


class RunCancelled(Exception):
    """The observer asked for a cancel; caught in execute(), never leaves run_report."""


def load_run_pack(cfg: CorelataConfig, profile: str | None) -> ResolvedPack:
    return load_pack(
        cfg.standards.default_pack,
        packs_dir=cfg.standards.packs_dir,
        profile=profile or cfg.standards.default_profile,
    )


class _Run:
    """One execution; holds the record and the mutable context."""

    def __init__(
        self,
        cfg: CorelataConfig,
        sources: list[Source],
        options: RunOptions,
        *,
        backends: dict[str, Backend],
        prompts: PromptLibrary,
        log: CallLog,
        pack: ResolvedPack,
        now: Callable[[], datetime],
        observer: RunObserver,
    ) -> None:
        self.now = now
        self.observer = observer
        self.log = log
        visible = model_view(sources)  # CRL-137: hidden text stays in the record only
        self.ctx = StageContext(
            cfg=cfg,
            runner=AgentRunner(cfg, backends, prompts, log),
            pack=pack,
            sources=visible,
            index=UnitIndex.from_sources(visible),
            value_statement=options.value_statement.strip(),
            extra_guidance=options.extra_guidance,
        )
        given = self._prior_reports(cfg, options.prior_reports)
        self.ctx.prior_reports = [r for r in given or [] if not r.cut]
        self.ctx.pack = pack.for_run(prior_reports=bool(self.ctx.prior_reports))
        if given == []:  # project memory, and the project has no accepted report
            self.ctx.initial_coverage = pack.prior_report_rules()
        self.max_iterations = (
            cfg.pipeline.max_iterations
            if options.max_iterations is None
            else options.max_iterations
        )
        self.checked = options.checked_report
        self.record = RunRecord(
            corelata_version=__version__,
            run_id=options.run_id or secrets.token_hex(6),
            kind=RunKind.REPORT if self.checked is None else RunKind.CHECK,
            checked_report=self.checked,
            created_at=options.created_at or now(),
            value_statement=self.ctx.value_statement,
            profile=pack.profile,
            parent_run_id=options.parent_run_id,
            extra_guidance=options.extra_guidance,
            pack_name=pack.name,
            pack_hash=pack_hash(pack),
            pack_snapshot=pack.model_dump(mode="json"),
            config_hash=config_hash(cfg),
            prompt_versions=prompts.versions(
                run_prompt_ids() if self.checked is None else check_prompt_ids()
            ),
            sources=sources,
            prior_reports=given or [],
            max_iterations=self.max_iterations,
            usage=log.usage(),
        )
        self.halved = False

    def _prior_reports(
        self, cfg: CorelataConfig, found: list[PriorReport] | None
    ) -> list[PriorReport] | None:
        """The earlier accepted reports this run is given (CRL-97), newest first, each marked
        `cut` or not by `pipeline.prior_judgments`; None without project memory."""
        limits = cfg.pipeline.prior_judgments
        if found is None or limits.max_reports == 0:
            return None
        return select_prior_reports(
            found,
            max_reports=limits.max_reports,
            budget_tokens=limits.budget_tokens,
            bytes_per_token=self.ctx.bytes_per_token("writer"),
        )

    async def stage[T](
        self,
        state: RunState,
        iteration: int,
        fn: Callable[[], Awaitable[T]],
        output: Callable[[T], dict[str, Any] | None] = lambda r: None,
    ) -> T:
        """Run one stage with the spec §7.5 retry ladder; record every attempt. A cancel the
        observer reports is honoured here, between stages, never inside a model call."""
        if await self.observer.cancel_requested():
            raise RunCancelled
        self.record.state = state
        await self.observer.state_changed(self.record)
        attempts = 0
        while True:
            started = self.now()
            attempts += 1
            try:
                result = await fn()
            except OVERSIZE_ERRORS as e:
                await self._record_stage(state, iteration, started, error=str(e))
                if self.halved:
                    raise
                self.halved = True
                self.ctx.cfg = self.ctx.cfg.model_copy(
                    update={
                        "pipeline": self.ctx.cfg.pipeline.model_copy(
                            update={
                                "digest_threshold_tokens": max(
                                    500, self.ctx.cfg.pipeline.digest_threshold_tokens // 2
                                ),
                                "digest_chunk_tokens": max(
                                    500, self.ctx.cfg.pipeline.digest_chunk_tokens // 2
                                ),
                                "writer_unit_budget_tokens": max(
                                    500, self.ctx.cfg.pipeline.writer_unit_budget_tokens // 2
                                ),
                            }
                        )
                    }
                )
                self.ctx.runner.cfg = self.ctx.cfg
                try:
                    await self._digest()
                except StageError as redigest:
                    await self._record_stage(state, iteration, self.now(), error=str(redigest))
                    raise
                continue
            except StageError as e:
                await self._record_stage(state, iteration, started, error=str(e))
                raise
            except AGENT_FAILURES as e:
                await self._record_stage(state, iteration, started, error=str(e))
                if attempts >= 2:
                    raise
                continue
            await self._record_stage(state, iteration, started, output=output(result))
            return result

    async def _record_stage(
        self,
        state: RunState,
        iteration: int,
        started: datetime,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        result = StageResult(
            stage=state.value,
            iteration=iteration,
            ok=error is None,
            output=output,
            error=error,
            started_at=started,
            finished_at=self.now(),
        )
        self.record.stages.append(result)
        await self.observer.stage_recorded(self.record, result)

    def _degradation(self, what: str, state: RunState, iteration: int, error: Exception) -> str:
        """R-M11-2: the line the report carries for a stage it was delivered without, counting
        the attempts `stage()` recorded as failed for that stage and iteration."""
        n = sum(
            1
            for s in self.record.stages
            if s.stage == state.value and s.iteration == iteration and not s.ok
        )
        # R-M11-7: one short line; the full text stays in the failed stage row and the trace
        first = " ".join(str(error).split("; ")[0].split())
        if len(first) > DEGRADATION_CHARS:
            first = first[: DEGRADATION_CHARS - 1] + "…"
        return f"{what} after {n} attempt{'' if n == 1 else 's'}: {first}"

    async def execute(self) -> RunRecord:
        if self.checked is not None:
            return await self._execute_check(self.checked)
        rec = self.record
        try:
            await self.stage(RunState.INGESTING, 0, self._ingest, lambda d: {"digested": sorted(d)})
            verdict = await self.stage(
                RunState.GATING, 0, lambda: run_gate(self.ctx), lambda v: v.model_dump()
            )
            rec.gate = verdict
            if not verdict.supported or verdict.substance is Substance.INSUFFICIENT:
                rec.state = RunState.GATE_REJECTED
                return self._finish()
            self.ctx.gate_evidence = list(verdict.evidence)
            if verdict.substance is Substance.THIN and verdict.suggested_scope:
                self.ctx.extra_guidance = (
                    f"{self.ctx.extra_guidance}\nThe gate judged the material thin. Scope note "
                    f"must include: {verdict.suggested_scope}"
                ).strip()
            iteration = 0
            prior: ReportBody | None = None
            draft: ReportBody | None = None
            next_stage = "drafting"
            findings: list[Finding] = []
            degradations: list[str] = []
            while True:
                routed = [f for f in open_findings(findings)]
                if next_stage == "drafting":
                    draft = await self.stage(
                        RunState.DRAFTING,
                        iteration,
                        lambda it=iteration, p=prior, r=routed: run_writer(
                            self.ctx,
                            iteration=it,
                            prior=p,
                            findings=[f for f in r if f.route_to == "writer"],
                        ),
                        lambda b: {
                            "title": b.title,
                            "claims": len(b.claims),
                            "withheld_units": len(self.ctx.withheld_refs),
                        },
                    )
                    rec.drafts.append(DraftRecord(role="writer", iteration=iteration, report=draft))
                assert draft is not None
                try:
                    draft = await self.stage(
                        RunState.CONVEYING,
                        iteration,
                        lambda it=iteration, d=draft, r=routed: run_conveyor(
                            self.ctx,
                            iteration=it,
                            draft=d,
                            findings=[f for f in r if f.route_to == "conveyor"],
                        ),
                        lambda b: {"title": b.title},
                    )
                except (*AGENT_FAILURES, StageError) as e:
                    # R-M11-2: the conveyor's input goes forward unedited and is audited
                    degradations.append(
                        self._degradation("conveyance skipped", RunState.CONVEYING, iteration, e)
                    )
                else:
                    rec.drafts.append(
                        DraftRecord(role="conveyor", iteration=iteration, report=draft)
                    )
                try:
                    outcome: AuditOutcome = await self.stage(
                        RunState.AUDITING,
                        iteration,
                        lambda it=iteration, d=draft: run_auditor(self.ctx, iteration=it, draft=d),
                        lambda o: {
                            "open": [f.id for f in open_findings(o.findings)],
                            "summary": o.summary,
                        },
                    )
                except (*AGENT_FAILURES, StageError) as e:
                    # R-M11-2: deliver with the previous audit's findings (none on iteration 0);
                    # R-M11-6: the engine's own checks still run on the delivered draft, and an
                    # earlier engine finding the revision fixed does not stay open (CRL-30,
                    # `merge_engine_findings`).
                    degradations.append(
                        self._degradation(AUDIT_INCOMPLETE, RunState.AUDITING, iteration, e)
                    )
                    engine = engine_only_findings(
                        draft, self.ctx.pack, iteration, self.ctx.quote_check()
                    )
                    findings = merge_engine_findings(findings, engine)
                    rec.findings.extend(engine)
                    break
                findings = outcome.findings
                rec.findings.extend(findings)
                next_stage = decide_next(findings, iteration, self.max_iterations)
                if next_stage == "rendering":
                    break
                iteration += 1
                prior = draft
            rec.iterations = iteration
            await self._deliver(draft, findings, degradations, iteration)
        except RunCancelled:
            rec.state = RunState.CANCELLED
        except (*AGENT_FAILURES, StageError) as e:
            rec.state = RunState.FAILED
            rec.error = str(e)
        return self._finish()

    async def _deliver(
        self, draft: ReportBody, findings: list[Finding], degradations: list[str], iteration: int
    ) -> None:
        """`rendering`: the delivered report with the engine's metadata, then `completed`."""
        rec = self.record
        still_open = open_findings(findings)
        degraded = still_open or degradations
        status = ReportStatus.FINDINGS_OPEN if degraded else ReportStatus.CLEAN
        rec.state = RunState.RENDERING
        await self.observer.state_changed(rec)
        started = self.now()
        rec.report = Report(
            **draft.model_dump(),
            metadata=ReportMetadata(
                run_id=rec.run_id,
                pack_name=rec.pack_name,
                pack_hash=rec.pack_hash,
                profile=rec.profile,
                iteration=iteration,
                status=status,
                open_findings=[f.id for f in still_open],
                degradations=degradations,
                prior_reports=[
                    PriorReportRef(run_id=r.run_id, title=r.title, accepted_at=r.accepted_at)
                    for r in self.ctx.prior_reports
                ],
            ),
        )
        await self._record_stage(
            RunState.RENDERING, iteration, started, output={"status": status.value}
        )
        rec.status = status
        rec.state = RunState.COMPLETED

    async def _execute_check(self, report: Source) -> RunRecord:
        """A check run (CRL-94): ingest → structuring → auditing → rendering, with no gate,
        writer, conveyor or loop. The structurer maps the report word for word; a structurer
        failure fails the run, as a writer's does, and an auditor failure degrades it, as in a
        run (R-M11-2). The delivered report is the checked one, with the audit's findings."""
        rec = self.record
        try:
            await self.stage(RunState.INGESTING, 0, self._ingest, lambda d: {"digested": sorted(d)})
            draft = await self.stage(
                RunState.STRUCTURING,
                0,
                lambda: run_structurer(self.ctx, report),
                lambda b: {
                    "title": b.title,
                    "claims": len(b.claims),
                    "unsourced": len(b.unsourced_claims()),
                },
            )
            rec.drafts.append(DraftRecord(role="structurer", iteration=0, report=draft))
            degradations: list[str] = []
            try:
                outcome: AuditOutcome = await self.stage(
                    RunState.AUDITING,
                    0,
                    lambda: run_auditor(self.ctx, iteration=0, draft=draft),
                    lambda o: {
                        "open": [f.id for f in open_findings(o.findings)],
                        "summary": o.summary,
                    },
                )
                findings = outcome.findings
            except (*AGENT_FAILURES, StageError) as e:
                degradations.append(self._degradation(AUDIT_INCOMPLETE, RunState.AUDITING, 0, e))
                findings = engine_only_findings(draft, self.ctx.pack, 0, self.ctx.quote_check())
            rec.findings.extend(findings)
            await self._deliver(draft, findings, degradations, 0)
        except RunCancelled:
            rec.state = RunState.CANCELLED
        except (*AGENT_FAILURES, StageError) as e:
            rec.state = RunState.FAILED
            rec.error = str(e)
        return self._finish()

    def _check_budgets(self) -> None:
        """Everything the writer may receive in full must leave room in its window (spec §7.4,
        §7.5): a non-digested source (≤ digest_threshold_tokens), a digest request
        (≤ digest_chunk_tokens) and the writer's unit budget."""
        writer = self.ctx.model_key("writer")
        window = self.ctx.cfg.models[writer].context_window
        limit = window - 2000
        p = self.ctx.cfg.pipeline
        budgets = (p.digest_threshold_tokens, p.digest_chunk_tokens, p.writer_unit_budget_tokens)
        if any(b > limit for b in budgets):
            raise StageError(
                "ingesting",
                f"pipeline.digest_threshold_tokens ({p.digest_threshold_tokens}), "
                f"pipeline.digest_chunk_tokens ({p.digest_chunk_tokens}) and "
                f"pipeline.writer_unit_budget_tokens ({p.writer_unit_budget_tokens}) must each "
                f"be at most {limit} for the writer model's context window ({window}); lower them",
            )

    async def _digest(self) -> None:
        """Spec §5.4 and §7.4: digest every source over the threshold, then the largest of the
        rest until the remaining non-digested sources fit the writer's unit budget, so the writer
        sees every source either in full or as a digest."""
        forced = writer_overflow(self.ctx)
        self.ctx.forced_digests = set(forced)
        self.ctx.digests = await run_digests(self.ctx, force=forced)
        self.record.digests = list(self.ctx.digests.values())

    async def _ingest(self) -> dict[str, Any]:
        self._check_budgets()
        await self._digest()
        return self.ctx.digests

    def _finish(self) -> RunRecord:
        self.record.usage = self.log.usage()
        self.record.llm_calls = list(self.log.records)
        return self.record


async def run_report(
    cfg: CorelataConfig,
    sources: list[Source],
    options: RunOptions,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    pack: ResolvedPack | None = None,
    now: Callable[[], datetime] = utcnow,
    observer: RunObserver | None = None,
) -> RunRecord:
    if not sources:
        raise ValueError("a run needs at least one source")
    if not options.value_statement.strip():
        raise ValueError("a run needs a value statement")
    if options.max_iterations is not None and not 0 <= options.max_iterations <= 10:
        raise ValueError("max_iterations must be between 0 and 10")
    if options.checked_report is not None:
        raise ValueError("a report run checks no report; use run_check")
    pack = pack or load_run_pack(cfg, options.profile)
    return await _Run(
        cfg,
        sources,
        options,
        backends=backends,
        prompts=prompts,
        log=log,
        pack=pack,
        now=now,
        observer=observer or NullObserver(),
    ).execute()


async def run_check(
    cfg: CorelataConfig,
    sources: list[Source],
    report: Source,
    options: RunOptions,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    pack: ResolvedPack | None = None,
    now: Callable[[], datetime] = utcnow,
    observer: RunObserver | None = None,
) -> RunRecord:
    """A check run (CRL-94): audit `report`, a finished report someone else wrote, against the
    pack with `sources` as its evidence. The value statement is optional; there is no project
    memory, no writer and no revision loop."""
    if not sources:
        raise ValueError("a check needs at least one source")
    if report.id != REPORT_ID:
        raise ValueError(f"the checked report's source id must be '{REPORT_ID}'")
    pack = pack or load_run_pack(cfg, options.profile)
    options = replace(options, checked_report=report, prior_reports=None, max_iterations=0)
    return await _Run(
        cfg,
        sources,
        options,
        backends=backends,
        prompts=prompts,
        log=log,
        pack=pack,
        now=now,
        observer=observer or NullObserver(),
    ).execute()


async def discover(
    cfg: CorelataConfig,
    sources: list[Source],
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    audience_hint: str = "",
    pack: ResolvedPack | None = None,
) -> DiscoveryResult:
    if not sources:
        raise ValueError("discovery needs at least one source")
    pack = pack or load_run_pack(cfg, None)
    visible = model_view(sources)  # CRL-137: no model reads hidden text
    ctx = StageContext(
        cfg=cfg,
        runner=AgentRunner(cfg, backends, prompts, log),
        pack=pack,
        sources=visible,
        index=UnitIndex.from_sources(visible),
        value_statement="",
    )
    ctx.digests = await run_digests(ctx)
    return await run_discovery(ctx, audience_hint)
