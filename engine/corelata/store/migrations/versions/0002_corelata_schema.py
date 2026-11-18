"""corelata schema (spec §8.3)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 12:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = postgresql.TIMESTAMP(timezone=True)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _identity() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False)


def _run_fk(**kw: object) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["run_id"], ["run.id"], ondelete="CASCADE", **kw)


def upgrade() -> None:
    """Create the Corelata tables."""
    op.create_table(
        "project",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("provenance", _jsonb(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_project_id"), "source", ["project_id"], unique=False)
    op.create_table(
        "source_unit",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("meta", _jsonb(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "ordinal"),
    )
    op.create_table(
        "run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("parent_run_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("value_statement", sa.Text(), nullable=False),
        sa.Column("extra_guidance", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=True),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("config_snapshot", _jsonb(), nullable=False),
        sa.Column("pack_name", sa.Text(), nullable=False),
        sa.Column("pack_hash", sa.Text(), nullable=False),
        sa.Column("pack_snapshot", _jsonb(), nullable=False),
        sa.Column("prompt_versions", _jsonb(), nullable=False),
        sa.Column("corelata_version", sa.Text(), nullable=False),
        sa.Column("docx_reference_key", sa.Text(), nullable=True),
        sa.Column("gate", _jsonb(), nullable=True),
        sa.Column("digests", _jsonb(), nullable=False),
        sa.Column("report", _jsonb(), nullable=True),
        sa.Column("token_usage", _jsonb(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("export_error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["parent_run_id"], ["run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_run_project_id"), "run", ["project_id"], unique=False)
    op.create_index(op.f("ix_run_state"), "run", ["state"], unique=False)
    op.create_table(
        "run_source",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        _run_fk(),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_run_source_source_id"), "run_source", ["source_id"], unique=False)
    op.create_table(
        "stage_result",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("output", _jsonb(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_stage_result_run_id"), "stage_result", ["run_id"], unique=False)
    op.create_table(
        "draft",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("report", _jsonb(), nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_draft_run_id"), "draft", ["run_id"], unique=False)
    op.create_table(
        "claim",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("likelihood_term", sa.Text(), nullable=True),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "claim_id"),
    )
    op.create_index(op.f("ix_claim_run_id"), "claim", ["run_id"], unique=False)
    op.create_table(
        "claim_evidence",
        sa.Column("claim_pk", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_ref", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_pk"], ["claim.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("claim_pk", "ordinal"),
    )
    op.create_table(
        "audit_finding",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("route_to", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("cited_units", _jsonb(), nullable=False),
        sa.Column("claim_ids", _jsonb(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_audit_finding_run_id"), "audit_finding", ["run_id"], unique=False)
    op.create_table(
        "llm_call",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request", _jsonb(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_llm_call_run_id"), "llm_call", ["run_id"], unique=False)
    op.create_table(
        "export",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "name"),
    )
    op.create_index(op.f("ix_export_run_id"), "export", ["run_id"], unique=False)
    op.create_table(
        "review_event",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("child_run_id", sa.UUID(), nullable=True),
        sa.Column("at", _TS, nullable=False),
        sa.ForeignKeyConstraint(["child_run_id"], ["run.id"], ondelete="SET NULL"),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_event_run_id"), "review_event", ["run_id"], unique=False)
    op.create_table(
        "discovery",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("audience_hint", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("llm_calls", _jsonb(), nullable=False),
        sa.Column("token_usage", _jsonb(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discovery_project_id"), "discovery", ["project_id"], unique=False)
    op.create_index(op.f("ix_discovery_state"), "discovery", ["state"], unique=False)
    op.create_table(
        "discovery_source",
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["discovery_id"], ["discovery.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("discovery_id", "ordinal"),
    )
    op.create_index(
        op.f("ix_discovery_source_source_id"), "discovery_source", ["source_id"], unique=False
    )
    op.create_table(
        "discovery_candidate",
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("evidence", _jsonb(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["discovery_id"], ["discovery.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("discovery_id", "ordinal"),
    )


_TABLES_REVERSED = (
    "discovery_candidate",
    "discovery_source",
    "discovery",
    "review_event",
    "export",
    "llm_call",
    "audit_finding",
    "claim_evidence",
    "claim",
    "draft",
    "stage_result",
    "run_source",
    "run",
    "source_unit",
    "source",
    "project",
)


def downgrade() -> None:
    """Drop the Corelata tables (indexes go with them)."""
    for name in _TABLES_REVERSED:
        op.drop_table(name)
