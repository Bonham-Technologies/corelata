"""Postgres schema (spec §8.3). JSONB columns hold Pydantic models dumped with mode="json";
their shapes are the exported schemas in schema/. Rows cascade from their project, so deleting
a project deletes everything that belongs to it. Copied from Coglossa; tables are Corelata's."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Dialect,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

Json = dict[str, Any]
JsonList = list[Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


_UNENCODABLE = re.compile("[\ud800-\udfff]")  # lone surrogates


def strip_nul(value: Any) -> Any:
    """Postgres rejects NUL characters in text and jsonb values, and model output can contain
    them (and lone surrogates, which `json.loads` accepts from a malformed escape but which
    cannot be encoded); every string written through these types loses its NUL characters and
    has unencodable surrogates replaced with U+FFFD instead of failing the transaction. Dict
    keys and nested lists are cleaned too."""
    if isinstance(value, str):
        return _UNENCODABLE.sub("\ufffd", value.replace("\x00", ""))
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [strip_nul(v) for v in value]
    return value


class SafeText(TypeDecorator[str]):
    """TEXT that drops NUL characters on write (see strip_nul)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return strip_nul(value)


class SafeJSONB(TypeDecorator[Any]):
    """JSONB that drops NUL characters from every string inside the value on write."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return strip_nul(value)


class Base(DeclarativeBase):
    type_annotation_map = {
        Json: SafeJSONB,
        JsonList: SafeJSONB,
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        str: SafeText,
    }


def _cascade(target: str, **kwargs: Any) -> Any:
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), **kwargs)


class Project(Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SourceRow(Base):
    """One uploaded file or one imported Coglossa run (spec §3, §5.1). A Coglossa export that
    carries a translation guide gives two rows sharing one stored file."""

    __tablename__ = "source"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id", index=True)
    kind: Mapped[str]  # SourceKind
    name: Mapped[str]
    format: Mapped[str]
    sha256: Mapped[str]
    storage_key: Mapped[str]
    provenance: Mapped[Json] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SourceUnitRow(Base):
    __tablename__ = "source_unit"
    source_id: Mapped[uuid.UUID] = _cascade("source.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str]
    text: Mapped[str]
    locator: Mapped[str]
    kind: Mapped[str]  # BlockKind
    meta: Mapped[Json] = mapped_column(default=dict)


class Run(Base):
    """Spec §8.3. `digests` lives here rather than in stage_result rows (spec §5.4) so the trace
    reads back without parsing stage output; the ingesting stage row still lists what was
    digested."""

    __tablename__ = "run"
    # the run list's order, newest first by (created_at, id) (CRL-39, migration 0006); it also
    # serves every other lookup by project, so project_id has no index of its own (CRL-58, 0007)
    __table_args__ = (
        Index("ix_run_project_created", "project_id", text("created_at DESC"), text("id DESC")),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id")
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL")
    )
    # RunKind (CRL-94, migration 0009): every run made before it reads as a report run
    kind: Mapped[str] = mapped_column(default="report", server_default="report")
    # the source a check run audits (CRL-94); NULL for a report run
    report_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(default="created", index=True)  # RunState
    status: Mapped[str | None]  # ReportStatus, completed runs only
    value_statement: Mapped[str]
    extra_guidance: Mapped[str] = mapped_column(default="")
    profile: Mapped[str | None]
    max_iterations: Mapped[int]
    iteration: Mapped[int] = mapped_column(default=0)
    config_hash: Mapped[str]
    config_snapshot: Mapped[Json]
    pack_name: Mapped[str]
    pack_hash: Mapped[str]
    pack_snapshot: Mapped[Json]
    prompt_versions: Mapped[Json]
    corelata_version: Mapped[str]
    docx_reference_key: Mapped[str | None]  # the profile's reference document, stored at submit
    gate: Mapped[Json | None]  # GateVerdict
    digests: Mapped[JsonList] = mapped_column(default=list)  # list[Digest]
    # list[PriorReport]: the earlier accepted reports the run was given (CRL-97, migration 0008);
    # NULL for a run made before it, read as none
    prior_reports: Mapped[JsonList | None]
    report: Mapped[Json | None]  # Report, delivered runs only
    token_usage: Mapped[Json | None]  # Usage, updated after every stage
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)  # executions the worker started
    error: Mapped[str | None]
    export_error: Mapped[str | None]  # the DOCX export failed after the run completed
    review_state: Mapped[Json | None]  # ReviewState JSON, written by review_run (CRL-17)
    # the database's clock, which the orphan sweep's grace is measured by (CRL-87); a SQL
    # expression rendered into the INSERT, not a server default, so the schema is unchanged
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class RunSource(Base):
    """The run's sources in order; ordinal n is source id "src<n>" inside the run's trace."""

    __tablename__ = "run_source"
    run_id: Mapped[uuid.UUID] = _cascade("run.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID] = _cascade("source.id", index=True)


class StageResultRow(Base):
    """One attempt of one stage (spec §8.3); `ordinal` is its position in the trace."""

    __tablename__ = "stage_result"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    stage: Mapped[str]
    iteration: Mapped[int]
    ok: Mapped[bool]
    output: Mapped[Json | None]
    error: Mapped[str | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]


class DraftRow(Base):
    __tablename__ = "draft"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    role: Mapped[str]
    iteration: Mapped[int]
    report: Mapped[Json]  # ReportBody


class ClaimRow(Base):
    """The delivered report's claims (spec §8.3 `claim`); drafts keep theirs in their JSON."""

    __tablename__ = "claim"
    __table_args__ = (UniqueConstraint("run_id", "claim_id"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    claim_id: Mapped[str]
    text: Mapped[str]
    kind: Mapped[str]
    likelihood_term: Mapped[str | None]


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    claim_pk: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("claim.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    unit_ref: Mapped[str]  # "<source_id>/<unit_id>" as the claim cites it
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source.id", ondelete="SET NULL")
    )
    unit_id: Mapped[str]


class AuditFindingRow(Base):
    __tablename__ = "audit_finding"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    iteration: Mapped[int]
    rule_id: Mapped[str]
    verdict: Mapped[str]
    severity: Mapped[str]
    route_to: Mapped[str]
    evidence: Mapped[str]
    cited_units: Mapped[JsonList] = mapped_column(default=list)
    claim_ids: Mapped[JsonList] = mapped_column(default=list)
    recommendation: Mapped[str] = mapped_column(default="")


class LLMCall(Base):
    __tablename__ = "llm_call"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    stage: Mapped[str]  # the run state when the call was made
    role: Mapped[str]
    backend: Mapped[str]
    model: Mapped[str]
    prompt_id: Mapped[str]
    prompt_version: Mapped[int]
    attempt: Mapped[int]
    ok: Mapped[bool]
    latency_ms: Mapped[int]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    error: Mapped[str | None]
    request: Mapped[Json | None]  # only when audit.store_llm_io
    response: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExportRow(Base):
    """A file the worker rendered for a finished run and put in storage (spec §7.2, §8.3)."""

    __tablename__ = "export"
    __table_args__ = (UniqueConstraint("run_id", "name"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    name: Mapped[str]  # trace.json, gate.json, report.json, report.md, report.html, report.docx
    storage_key: Mapped[str]
    sha256: Mapped[str]
    size: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReviewEvent(Base):
    """Spec §10.1 review actions; a `return` links the run it created."""

    __tablename__ = "review_event"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    action: Mapped[str]  # accept | return
    note: Mapped[str] = mapped_column(default="")
    actor: Mapped[str | None]
    child_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(default=utcnow)


class Discovery(Base):
    """Spec §7.1: a discovery job; its model calls are few, so they live in a JSON column."""

    __tablename__ = "discovery"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id", index=True)
    audience_hint: Mapped[str] = mapped_column(default="")
    state: Mapped[str] = mapped_column(default="created", index=True)  # DiscoveryState
    error: Mapped[str | None]
    llm_calls: Mapped[JsonList] = mapped_column(default=list)  # list[LLMCallRecord]
    token_usage: Mapped[Json | None]  # Usage
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class DiscoverySource(Base):
    __tablename__ = "discovery_source"
    discovery_id: Mapped[uuid.UUID] = _cascade("discovery.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID] = _cascade("source.id", index=True)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidate"
    discovery_id: Mapped[uuid.UUID] = _cascade("discovery.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str]
    audience: Mapped[str]
    evidence: Mapped[JsonList] = mapped_column(default=list)
    confidence_note: Mapped[str] = mapped_column(default="")
