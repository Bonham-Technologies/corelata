"""The run state machine and the trace record `corelata run` writes (spec §7.2, §8.3)."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from corelata.schema.audit import Finding
from corelata.schema.common import LLMCallRecord, Usage
from corelata.schema.digest import Digest
from corelata.schema.gate import GateVerdict
from corelata.schema.report import PriorReport, Report, ReportBody, ReportStatus
from corelata.schema.source import Source


def _empty(items: list) -> bool:
    return not items


class RunState(StrEnum):
    CREATED = "created"
    INGESTING = "ingesting"
    GATING = "gating"
    DRAFTING = "drafting"
    CONVEYING = "conveying"
    AUDITING = "auditing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    GATE_REJECTED = "gate_rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {RunState.COMPLETED, RunState.GATE_REJECTED, RunState.FAILED, RunState.CANCELLED}
)


class StageResult(BaseModel):
    stage: str
    iteration: int
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class DraftRecord(BaseModel):
    role: str
    iteration: int
    report: ReportBody


class RunRecord(BaseModel):
    schema_version: Literal["1"] = "1"
    corelata_version: str
    run_id: str
    created_at: datetime
    state: RunState = RunState.CREATED
    status: ReportStatus | None = None
    value_statement: str
    profile: str | None = None
    parent_run_id: str | None = None  # the run this one reruns (review "return" or rejection)
    extra_guidance: str = ""  # additional writer guidance the analyst or a reviewer supplied
    pack_name: str
    pack_hash: str
    pack_snapshot: dict[str, Any]
    config_hash: str
    prompt_versions: dict[str, int]
    sources: list[Source] = Field(default_factory=list)
    digests: list[Digest] = Field(default_factory=list)
    # CRL-97: the project's earlier accepted reports the run was given, newest first, those the
    # budget left out marked `cut`; left out of the dump when there are none.
    prior_reports: list[PriorReport] = Field(default_factory=list, exclude_if=_empty)
    gate: GateVerdict | None = None
    stages: list[StageResult] = Field(default_factory=list)
    drafts: list[DraftRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    report: Report | None = None
    iterations: int = 0
    max_iterations: int
    usage: Usage
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    error: str | None = None
