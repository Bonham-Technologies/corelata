"""The writer's and conveyor's schema source, built per call (R-M12-1, R-M13-3): `ReportBody`
with `Claim.evidence` restricted to the run's unit ids and `SourceEntry.source_id` to its source
ids, so a server configured `json_schema` cannot let a model cite a source id (`src1`) or an
invented ref as a unit, or list a source the run does not have. The variant keeps the field
names, order and descriptions and the schema name (`ReportBody`); only those two fields differ,
each as one enum in `$defs` (`UnitRef`, `SourceId`; plain strings above
`audit_schema.ENUM_LIMIT` ids, and an empty evidence list when there are no units). The per-call
type is only a schema source: replies are parsed as the canonical `ReportBody`, so `check_refs`
and the sources check report a bad id in the same repair message as every other validator error
(R-M12-8); a `json_schema` server still cannot generate one."""

from collections.abc import Sequence
from typing import Any

from pydantic import Field, create_model

from corelata.schema.report import (
    Claim,
    ClaimCore,
    JudgmentChange,
    Quote,
    ReportBody,
    ReportBodyCore,
    ReportBodyWithChanges,
    SourceEntry,
    SourceEntryCore,
    SourceSummaryStatement,
)
from corelata.stages.audit_schema import enum_item, enum_list


def _quotes_field(unit_refs: Sequence[str]) -> tuple[Any, Any]:
    """`Claim.quotes` with each quote's `ref` drawn from the same `UnitRef` enum as `evidence`
    (CRL-93); with no units the list must be empty, like `evidence`."""
    description = Claim.model_fields["quotes"].description
    if not unit_refs:
        return (list[Quote], Field(default_factory=list, max_length=0, description=description))
    quote = create_model(
        "Quote",
        __base__=Quote,
        __doc__=Quote.__doc__,
        # no description: OpenAI's strict subset refuses keywords next to a `$ref`
        ref=(enum_item("UnitRef", unit_refs), ...),
    )
    return (list[quote], Field(default_factory=list, description=description))


def _changes_field(prior_run_ids: Sequence[str]) -> tuple[Any, Any]:
    """`ReportBody.changes_from_previous` with each entry's `prior_run_id` drawn from the run
    ids of the earlier reports the writer was given (`PriorRunId`, CRL-97)."""
    change = create_model(
        "JudgmentChange",
        __base__=JudgmentChange,
        __doc__=JudgmentChange.__doc__,
        # no description: OpenAI's strict subset refuses keywords next to a `$ref`
        prior_run_id=(enum_item("PriorRunId", prior_run_ids), ...),
    )
    description = ReportBody.model_fields["changes_from_previous"].description
    return (list[change], Field(default_factory=list, description=description))


def report_output_type(
    unit_refs: Sequence[str],
    source_ids: Sequence[str],
    *,
    quotes: bool = False,
    access_terms: Sequence[str] = (),
    summary: bool = False,
    prior_run_ids: Sequence[str] = (),
) -> type[ReportBodyCore]:
    """`unit_refs` are the refs `StageContext.check_refs` accepts: `ctx.index.refs()`, every
    unit of every source, digested or not. `source_ids` are the ids `report_validator` accepts:
    the run's sources, in order. Subclassing keeps `ReportBody`'s claim-id validator. `quotes`
    (`pipeline.evidence_quotes` is not `off`, CRL-93) adds `Claim.quotes`; without it the claim
    is built on `ClaimCore`, so the schema is the one a run sent before quotes existed.
    `access_terms` (the lexicon's `source_access`, CRL-96) adds each source entry's date of
    information, origin and `access`, an enum of those terms (`SourceAccess`); `summary` (the
    template has a `source_summary` section) adds `source_summary`, whose source lists draw on
    the same `SourceId` enum as `source_id`. Without either the schema is the one sent before
    CRL-96. `prior_run_ids` (the earlier accepted reports the writer reads, CRL-97) adds
    `changes_from_previous`, on `ReportBodyWithChanges`; without them the body is built on
    `ReportBodyCore`, so the schema is the one a run sent before project memory existed."""
    evidence = enum_list(
        "UnitRef", unit_refs, description=Claim.model_fields["evidence"].description
    )
    if quotes:
        claim = create_model(
            "Claim",
            __base__=Claim,
            __doc__=Claim.__doc__,
            evidence=evidence,
            quotes=_quotes_field(unit_refs),
        )
    else:
        claim = create_model("Claim", __base__=ClaimCore, __doc__=Claim.__doc__, evidence=evidence)
    # A run always has at least one source, so `source_ids` is never empty and needs no
    # `maxItems: 0` rule; `enum_item` gives a plain string above ENUM_LIMIT ids. One enum serves
    # every field that names a source, so the schema lists the ids once.
    source_id = enum_item("SourceId", source_ids)
    if access_terms:
        source = create_model(
            "SourceEntry",
            __base__=SourceEntry,
            __doc__=SourceEntry.__doc__,
            source_id=(source_id, ...),
            # no description: OpenAI's strict subset refuses keywords next to a `$ref`
            access=(enum_item("SourceAccess", access_terms), ...),
        )
    else:
        source = create_model(
            "SourceEntry",
            __base__=SourceEntryCore,
            __doc__=SourceEntry.__doc__,
            source_id=(source_id, ...),
        )
    fields: dict[str, Any] = {"sources": (list[source], ...), "claims": (list[claim], ...)}
    if prior_run_ids:
        fields["changes_from_previous"] = _changes_field(prior_run_ids)
    if summary:
        fields["source_summary"] = (_summary_model(source_id), ...)
    return create_model(
        "ReportBody",
        __base__=ReportBodyWithChanges if prior_run_ids else ReportBodyCore,
        __doc__=ReportBody.__doc__,
        **fields,
    )


def _summary_model(source_id: Any) -> type[SourceSummaryStatement]:
    def ids(name: str) -> tuple[Any, Any]:
        description = SourceSummaryStatement.model_fields[name].description
        return (list[source_id], Field(default_factory=list, description=description))

    return create_model(
        "SourceSummaryStatement",
        __base__=SourceSummaryStatement,
        __doc__=SourceSummaryStatement.__doc__,
        key_sources=ids("key_sources"),
        conflicting_sources=ids("conflicting_sources"),
    )
