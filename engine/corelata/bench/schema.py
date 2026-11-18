"""What `corelata bench` reports (spec §13): one result per scenario run, rule tallies across
runs, and agreement rates. Exported as `bench-report.schema.json`."""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from corelata.schema import ReportStatus, RunState, Substance


class Rate(BaseModel):
    """Agreements over decided cases; a case the scenario does not specify is not counted."""

    agree: int = 0
    total: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ratio(self) -> float | None:
        return None if self.total == 0 else round(self.agree / self.total, 4)

    def add(self, agreed: bool | None) -> None:
        if agreed is None:
            return
        self.total += 1
        self.agree += int(agreed)


class RuleTally(BaseModel):
    """How one rule behaved across every audited iteration the scenarios specify."""

    expected: int = 0  # times the rule was expected to fail
    hit: int = 0  # expected and did fail
    missed: int = 0  # expected, did not fail (or the iteration was never audited)
    unexpected: int = 0  # failed in an iteration that did not expect it


class GateResult(BaseModel):
    """The gate's verdict in one run (R-M12-6), so a reader sees why a run stopped there."""

    supported: bool
    substance: Substance
    reasons: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    repeat: int
    ok: bool  # the run produced a record (even a failed one); False means an exception
    error: str | None = None
    state: RunState | None = None
    status: ReportStatus | None = None
    iterations: int | None = None
    gate: GateResult | None = None  # None: the run errored, or ended before the gate answered
    duration_s: float = 0.0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    mismatches: list[str] = Field(default_factory=list)  # from scenarios.compare
    gate_agree: bool | None = None  # None: the scenario does not specify the gate
    rules_agree: bool | None = None  # None: the scenario lists no failing rules
    state_agree: bool | None = None  # None only for an errored run

    @property
    def agree(self) -> bool:
        return self.ok and not self.mismatches


class ScenarioResult(BaseModel):
    name: str
    description: str
    runs: list[RunResult]


class BenchSummary(BaseModel):
    scenarios: int
    runs: int
    errors: int
    full_agreement: Rate  # compare() found nothing to object to
    gate_agreement: Rate
    rule_agreement: Rate
    state_agreement: Rate
    tokens_in: int
    tokens_out: int
    duration_s: float


class BenchReport(BaseModel):
    corelata_version: str
    started_at: datetime
    finished_at: datetime
    config_hash: str
    models: dict[str, str]  # role -> model id sent to the server
    scenarios_dir: str
    repeat: int
    scenarios: list[ScenarioResult]
    rules: dict[str, RuleTally]  # rule id -> tally, sorted by id
    summary: BenchSummary
