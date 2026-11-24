"""Scenario fixtures (spec §13): sources plus a statement plus what the run must do. CI runs the
synthetic set against the synthetic model; `corelata bench` (M6) runs a set against real models
and reports agreement. The synthetic set states exact outcomes; the real-model set (M12) states
ranges and rule sets, because a real model may take more than one acceptable path. Loading,
running and comparing live here so both callers share one truth."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from corelata.config import CorelataConfig, PipelineConfig
from corelata.ingest.units import source_from_html, source_from_paragraphs
from corelata.llm.agent import CallLog
from corelata.llm.types import Backend
from corelata.pipeline import AUDIT_INCOMPLETE, RunOptions, run_report, utcnow
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    Finding,
    Report,
    ReportStatus,
    RunRecord,
    RunState,
    Source,
    Substance,
    Verdict,
)
from corelata.stages.audit import ENGINE_CHECK


class ScenarioError(ValueError):
    """A scenario file is unusable; the message names the file and the problem."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioSource(_Strict):
    """Plain-text `paragraphs`, one unit each, or an `html` page read as ingest reads an HTML
    file, hidden text and all (CRL-137)."""

    id: str
    name: str | None = None
    paragraphs: list[str] | None = Field(None, min_length=1)
    html: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def _one_body(self) -> "ScenarioSource":
        if (self.paragraphs is None) == (self.html is None):
            raise ValueError("set paragraphs or html, not both")
        return self


# An exact expectation and its range form (R-M12-5): a scenario sets one or the other.
_PAIRS = (
    ("state", "state_in"),
    ("status", "status_in"),
    ("iterations", "iterations_max"),
    ("gate_supported", "gate_supported_in"),
    ("substance", "substance_in"),
)


class ScenarioExpect(_Strict):
    """What the run must do (R-M12-5). Exact fields and range fields can be mixed, never a field
    and its range form. `status_in` is read only when the run delivered a report. Rules are
    stated either per iteration (`failing_rules`, exact) or as sets: `rules_must_pass` never
    fail in the last audited iteration, `rules_must_fail` fail in at least one audited
    iteration, and `rules_may_fail` lists what else may fail at the end; with
    `rules_may_fail: null` (the default) other rules are free, with a list (even empty) any
    other failure at the end is a mismatch."""

    state: RunState | None = None
    state_in: list[RunState] | None = Field(None, min_length=1)
    status: ReportStatus | None = None
    status_in: list[ReportStatus] | None = Field(None, min_length=1)
    iterations: int | None = None
    iterations_max: int | None = Field(None, ge=0, le=10)
    gate_supported: bool | None = None
    gate_supported_in: list[bool] | None = Field(None, min_length=1)
    substance: Substance | None = None
    substance_in: list[Substance] | None = Field(None, min_length=1)
    failing_rules: dict[int, list[str]] = Field(default_factory=dict)
    rules_must_pass: list[str] = Field(default_factory=list)
    rules_may_fail: list[str] | None = None
    rules_must_fail: list[str] = Field(default_factory=list)
    open_findings: list[str] | None = None
    digested: list[str] | None = None
    # CRL-96: the delivered report's source summary names at least these sources as conflicting
    conflicting_sources: list[str] | None = Field(None, min_length=1)
    # CRL-137: exactly these unit refs are marked hidden (no model reads them) and suspect (their
    # text reads as an instruction to an AI system); and none of these words, in any case, are in
    # the delivered report's title or key judgments, where an obeyed instruction would show
    hidden_units: list[str] | None = None
    suspect_units: list[str] | None = None
    report_excludes: list[str] | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def _one_form_each(self) -> "ScenarioExpect":
        for exact, ranged in _PAIRS:
            if getattr(self, exact) is not None and getattr(self, ranged) is not None:
                raise ValueError(f"set {exact} or {ranged}, not both")
        if self.state is None and self.state_in is None:
            raise ValueError("set state or state_in")
        sets = self.rule_sets()
        if self.failing_rules and sets:
            raise ValueError(f"set failing_rules or {', '.join(sets)}, not both")
        clash = sorted(set(self.rules_must_pass) & set(self.rules_may_fail or []))
        if clash:
            raise ValueError(f"{', '.join(clash)} in both rules_must_pass and rules_may_fail")
        return self

    def rule_sets(self) -> list[str]:
        """The `rules_*` fields this scenario sets (an empty `rules_may_fail` list is set)."""
        named = []
        if self.rules_must_pass:
            named.append("rules_must_pass")
        if self.rules_may_fail is not None:
            named.append("rules_may_fail")
        if self.rules_must_fail:
            named.append("rules_must_fail")
        return named

    def expects_gate(self) -> bool:
        ranged = (self.gate_supported, self.gate_supported_in, self.substance, self.substance_in)
        return any(v is not None for v in ranged)


class Scenario(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    statement: str = Field(min_length=1)
    sources: list[ScenarioSource] = Field(min_length=1)
    max_iterations: int | None = Field(None, ge=0, le=10)
    profile: str | None = None
    pipeline: dict[str, Any] = Field(default_factory=dict)
    expect: ScenarioExpect


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"{path.name}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ScenarioError(f"{path.name}: cannot read: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{path.name}: expected a mapping at the top level")
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as e:
        raise ScenarioError(f"{path.name}: {_first_error(e)}") from e
    try:  # an unknown key or a bad value fails here, not when the scenario runs
        PipelineConfig.model_validate({**PipelineConfig().model_dump(), **scenario.pipeline})
    except ValidationError as e:
        raise ScenarioError(f"{path.name}: pipeline.{_first_error(e)}") from e
    return scenario


def _first_error(e: ValidationError) -> str:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "(top level)"
    return f"{where}: {first['msg']}"


def load_scenarios(directory: Path) -> list[Scenario]:
    if not directory.is_dir():
        return []
    return [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]


def scenario_sources(scenario: Scenario) -> list[Source]:
    return [
        source_from_html(s.id, s.html, name=s.name)
        if s.html is not None
        else source_from_paragraphs(s.id, s.paragraphs or [], name=s.name)
        for s in scenario.sources
    ]


async def run_scenario(
    scenario: Scenario,
    cfg: CorelataConfig,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    now: Callable[[], datetime] = utcnow,
) -> RunRecord:
    if scenario.pipeline:
        pipeline = PipelineConfig.model_validate({**cfg.pipeline.model_dump(), **scenario.pipeline})
        cfg = cfg.model_copy(update={"pipeline": pipeline})
    return await run_report(
        cfg,
        scenario_sources(scenario),
        RunOptions(
            value_statement=scenario.statement,
            profile=scenario.profile,
            max_iterations=scenario.max_iterations,
            run_id=scenario.name,
        ),
        backends=backends,
        prompts=prompts,
        log=log,
        now=now,
    )


def meets(exact: object, allowed: list[Any] | None, actual: object) -> bool:
    """`actual` satisfies an exact expectation and its range form (either may be unset)."""
    return (exact is None or exact == actual) and (allowed is None or actual in allowed)


def audited_iterations(record: RunRecord) -> set[int]:
    """The iterations whose audit completed (R-M12-5). A finding carries its iteration, but a
    degraded audit (R-M11-2) leaves only the engine's own findings for it (R-M11-6), or none,
    and the report says "audit incomplete" for the run's last iteration; neither counts. A
    skipped conveyance does not touch the audit, so its iteration counts."""
    by_iteration: dict[int, list[Finding]] = {}
    for f in record.findings:
        by_iteration.setdefault(f.iteration, []).append(f)
    incomplete = record.report is not None and any(
        line.startswith(AUDIT_INCOMPLETE) for line in record.report.metadata.degradations
    )
    return {
        iteration
        for iteration, found in by_iteration.items()
        if not all(f.evidence.startswith(ENGINE_CHECK) for f in found)
        and not (incomplete and iteration == record.iterations)
    }


def delivered_unaudited(record: RunRecord, audited: set[int]) -> bool:
    """The run delivered a report but its last iteration's audit did not complete (R-M12-10)."""
    return record.report is not None and record.iterations not in audited


def failed_rules(record: RunRecord, iteration: int) -> set[str]:
    return {
        f.rule_id for f in record.findings if f.iteration == iteration and f.verdict is Verdict.FAIL
    }


def compare(scenario: Scenario, record: RunRecord) -> list[str]:
    """Every way the record disagrees with the scenario's expectations; empty means it passed."""
    e = scenario.expect
    out: list[str] = []

    def check(label: str, expected: object, actual: object) -> None:
        if expected is not None and expected != actual:
            out.append(f"{label}: expected {_show(expected)}, got {_show(actual)}")

    def within(label: str, allowed: list[Any] | None, actual: object) -> None:
        if allowed is not None and actual not in allowed:
            out.append(f"{label}: expected one of {_show_all(allowed)}, got {_show(actual)}")

    check("state", e.state, record.state)
    within("state", e.state_in, record.state)
    check("status", e.status, record.status)
    if record.report is not None:  # status_in speaks only of a delivered report
        within("status", e.status_in, record.status)
    check("iterations", e.iterations, record.iterations)
    if e.iterations_max is not None and record.iterations > e.iterations_max:
        out.append(f"iterations: expected at most {e.iterations_max}, got {record.iterations}")
    if record.gate is None:
        if e.expects_gate():
            out.append("gate: expected a verdict, got none")
    else:
        check("gate.supported", e.gate_supported, record.gate.supported)
        within("gate.supported", e.gate_supported_in, record.gate.supported)
        check("gate.substance", e.substance, record.gate.substance)
        within("gate.substance", e.substance_in, record.gate.substance)
    pack_rules = {r["id"] for r in record.pack_snapshot.get("rules", [])}
    audited = audited_iterations(record)
    for it, rules in sorted(e.failing_rules.items()):
        unknown = sorted(set(rules) - pack_rules)
        if unknown:
            out.append(f"failing_rules[{it}]: not in pack: {', '.join(unknown)}")
        if it not in audited:
            out.append(f"failing_rules[{it}]: no audit ran for iteration {it}")
            continue
        check(f"failing_rules[{it}]", sorted(rules), sorted(failed_rules(record, it)))
    out += _compare_rule_sets(e, record, pack_rules, audited)
    if e.open_findings is not None:
        actual_open = sorted(record.report.metadata.open_findings) if record.report else []
        check("open_findings", sorted(e.open_findings), actual_open)
    if e.digested is not None:
        check("digested", sorted(e.digested), sorted(d.source_id for d in record.digests))
    if e.conflicting_sources is not None:
        out += _compare_conflict(e.conflicting_sources, record)
    for label, key, expected in (
        ("hidden_units", "hidden", e.hidden_units),
        ("suspect_units", "suspect", e.suspect_units),
    ):
        if expected is not None:
            check(label, sorted(expected), _marked(record, key))
    if e.report_excludes is not None and record.report is not None:
        out += _compare_excludes(e.report_excludes, record.report)
    return out


def _marked(record: RunRecord, key: str) -> list[str]:
    """The refs of the record's units whose `meta[key]` is set (CRL-137)."""
    return sorted(f"{s.id}/{u.id}" for s in record.sources for u in s.units if u.meta.get(key))


def _compare_excludes(words: list[str], report: Report) -> list[str]:
    shown = " ".join([report.title, *(kj.text for kj in report.key_judgments)]).casefold()
    found = [w for w in words if w.casefold() in shown]
    if not found:
        return []
    return [f"report_excludes: the title or key judgments say {_show_all(found)}"]


def _compare_conflict(expected: list[str], record: RunRecord) -> list[str]:
    summary = record.report.source_summary if record.report is not None else None
    if summary is None:
        return ["conflicting_sources: the report has no source summary"]
    missing = sorted(set(expected) - set(summary.conflicting_sources))
    if not missing:
        return []
    named = ", ".join(summary.conflicting_sources) or "none"
    return [f"conflicting_sources: not named as conflicting: {', '.join(missing)} (named: {named})"]


def _compare_rule_sets(
    e: ScenarioExpect, record: RunRecord, pack_rules: set[str], audited: set[int]
) -> list[str]:
    if not e.rule_sets():
        return []
    out: list[str] = []
    named = (
        ("rules_must_pass", e.rules_must_pass),
        ("rules_may_fail", e.rules_may_fail or []),
        ("rules_must_fail", e.rules_must_fail),
    )
    for label, rules in named:
        unknown = sorted(set(rules) - pack_rules)
        if unknown:
            out.append(f"{label}: not in pack: {', '.join(unknown)}")
    if not audited:
        if record.state is RunState.COMPLETED:  # an earlier end is the state check's business
            out.append("rules: no audit ran")
        return out
    ever = set().union(*(failed_rules(record, it) for it in audited))
    never = sorted(set(e.rules_must_fail) - ever)
    final = max(audited)
    last = failed_rules(record, final)
    if delivered_unaudited(record, audited):
        # R-M12-10: the delivered draft's audit degraded, so what an earlier draft failed says
        # nothing about the report: must-pass and the closed may-fail set are not scored
        out.append(
            f"rules: no audit of the delivered draft (iteration {record.iterations} degraded)"
        )
        if never:
            out.append(f"rules_must_fail: never failed: {', '.join(never)}")
        return out
    must_have_passed = sorted(set(e.rules_must_pass) & last)
    if must_have_passed:
        out.append(f"rules_must_pass: failed in iteration {final}: {', '.join(must_have_passed)}")
    if never:
        out.append(f"rules_must_fail: never failed: {', '.join(never)}")
    if e.rules_may_fail is not None:
        allowed = set(e.rules_may_fail) | set(e.rules_must_fail) | set(e.rules_must_pass)
        extra = sorted(last - allowed)
        if extra:
            out.append(f"rules: unexpected failure in iteration {final}: {', '.join(extra)}")
    return out


def _show(value: object) -> str:
    if hasattr(value, "value"):  # enums print as their wire value
        return repr(value.value)
    return repr(value)


def _show_all(values: list[Any]) -> str:
    return "[" + ", ".join(_show(v) for v in values) + "]"
