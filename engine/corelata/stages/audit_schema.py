"""The auditor's output schema, built per call (R-M11-1): `findings` is an object with one
required property per rule id, each allowing only the verdicts its checkability permits and,
while the lists are short enough to enumerate, only the unit refs and claim ids in scope. A
server configured `json_schema` enforces it while generating, so an advisory rule cannot be
passed, an invented rule id means nothing and a source id cannot be cited as a unit.
Pydantic parsing enforces the shape on every server (required rule keys, verdict literals);
`audit_validator` stays as the backstop on the converted output, adding the unit-ref check and
defending the `AuditOutput` contract.

The unit refs and the claim ids are each one `StrEnum` in `$defs` that every field citing them
refers to (R-M12-1). `enum_list` builds those fields and `enum_item` a single id; the writer's
schema (`report_schema.py`) uses both."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from corelata.schema import AuditOutput, FindingOut, Verdict
from corelata.standards.schema import Checkability, ResolvedPack

# Above this many refs or claim ids the lists stay plain strings: an enum that long slows
# constrained decoding more than it helps, and the validator still checks every ref.
ENUM_LIMIT = 200

_VERDICTS = {
    Checkability.VERIFIABLE: (Verdict.PASS.value, Verdict.FAIL.value, Verdict.NOT_APPLICABLE.value),
    Checkability.ADVISORY: (Verdict.ATTESTED.value, Verdict.NOT_APPLICABLE.value),
}
_NAMES = {Checkability.VERIFIABLE: "VerifiableFinding", Checkability.ADVISORY: "AdvisoryFinding"}


def enum_item(name: str, values: Sequence[str]) -> Any:
    """The type of one id drawn from `values`: a `StrEnum` called `name` up to ENUM_LIMIT values,
    which the JSON schema emits once in `$defs` however many fields use it, else `str` (above the
    limit, or with no values; `enum_list` makes an empty list's field empty instead). ENUM_LIMIT is
    read on every call, so a test can lower it."""
    if not values or len(values) > ENUM_LIMIT:
        return str
    return StrEnum(name, [(f"v{i}", value) for i, value in enumerate(values)])


def enum_list(
    name: str, values: Sequence[str], *, description: str | None = None
) -> tuple[Any, Any]:
    """A `create_model` field definition for a list of `values`: items of `enum_item(name,
    values)`; with no values the list must be empty (R-M11-8)."""
    if not values:
        return (list[str], Field(default_factory=list, max_length=0, description=description))
    return (list[enum_item(name, values)], Field(default_factory=list, description=description))


def _finding_model(kind: Checkability, unit: Any, claim: Any) -> type[BaseModel]:
    """`unit` and `claim` are `enum_list` fields, shared by both finding models."""
    return create_model(
        _NAMES[kind],
        verdict=(Literal[_VERDICTS[kind]], ...),
        evidence=(str, ...),
        cited_units=unit,
        claim_ids=claim,
        recommendation=(str, ""),
    )


def audit_output_type(
    pack: ResolvedPack, unit_refs: list[str], claim_ids: list[str]
) -> type[BaseModel]:
    unit, claim = enum_list("UnitRef", unit_refs), enum_list("ClaimId", claim_ids)
    models = {kind: _finding_model(kind, unit, claim) for kind in Checkability}
    fields: dict[str, Any] = {
        f"r{i}": (models[r.checkability], Field(alias=r.id)) for i, r in enumerate(pack.rules)
    }
    findings = create_model(
        "AuditFindings",
        __config__=ConfigDict(
            populate_by_name=True, json_schema_extra={"additionalProperties": False}
        ),
        **fields,
    )
    return create_model("AuditByRule", findings=(findings, ...), summary=(str, ...))


def to_audit_output(parsed: BaseModel, pack: ResolvedPack) -> AuditOutput:
    """The list form everything downstream reads: one `FindingOut` per rule, in pack order, with
    plain-string refs and claim ids (`mode="json"` turns the enum members into their values)."""
    by_rule = parsed.findings  # an AuditFindings built by audit_output_type for this pack
    return AuditOutput(
        findings=[
            FindingOut(rule_id=r.id, **getattr(by_rule, f"r{i}").model_dump(mode="json"))
            for i, r in enumerate(pack.rules)
        ],
        summary=parsed.summary,
    )
