import json
from enum import StrEnum

import pytest
from pydantic import ValidationError

from corelata.schema import AuditOutput, Verdict
from corelata.stages import audit_schema
from corelata.stages.audit_schema import (
    ENUM_LIMIT,
    audit_output_type,
    enum_item,
    enum_list,
    to_audit_output,
)
from corelata.standards.schema import Checkability

REFS = ["src1/u1", "src1/u2", "src2/u1"]
CLAIMS = ["c0", "c1"]


def _reply(pack) -> dict:
    return {
        "findings": {
            r.id: {
                "verdict": "attested" if r.checkability is Checkability.ADVISORY else "pass",
                "evidence": f"e-{r.id}",
            }
            for r in pack.rules
        },
        "summary": "s",
    }


def test_every_rule_id_is_a_required_property_of_findings(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    schema = model.model_json_schema()
    findings = schema["$defs"]["AuditFindings"]
    assert findings["required"] == pack.rule_ids()
    assert findings["additionalProperties"] is False
    assert list(findings["properties"]) == pack.rule_ids()
    assert schema["required"] == ["findings", "summary"] and model.__name__ == "AuditByRule"


def test_verdicts_are_restricted_by_checkability(pack):
    schema = audit_output_type(pack, REFS, CLAIMS).model_json_schema()
    props = schema["$defs"]["AuditFindings"]["properties"]
    assert {r.checkability for r in pack.rules} == set(Checkability)  # the pack has both kinds
    for r in pack.rules:
        name = props[r.id]["$ref"].rsplit("/", 1)[1]
        verdict = schema["$defs"][name]["properties"]["verdict"]
        if r.checkability is Checkability.ADVISORY:
            assert verdict["enum"] == ["attested", "not_applicable"], r.id
        else:
            assert verdict["enum"] == ["pass", "fail", "not_applicable"], r.id


def test_cited_units_and_claim_ids_are_one_enum_each_up_to_the_limit(pack):
    def shape(refs, claims):
        defs = audit_output_type(pack, refs, claims).model_json_schema()["$defs"]
        return (
            defs,
            defs["VerifiableFinding"]["properties"],
            defs["AdvisoryFinding"]["properties"],
        )

    defs, verifiable, advisory = shape(REFS, CLAIMS)
    for props in (verifiable, advisory):  # both finding models point at the same two defs
        assert props["cited_units"]["items"] == {"$ref": "#/$defs/UnitRef"}
        assert props["claim_ids"]["items"] == {"$ref": "#/$defs/ClaimId"}
    assert defs["UnitRef"] == {"enum": REFS, "title": "UnitRef", "type": "string"}
    assert defs["ClaimId"] == {"enum": CLAIMS, "title": "ClaimId", "type": "string"}
    assert json.dumps(defs).count('"src1/u2"') == 1  # emitted once, not once per finding model
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    defs, _, _ = shape(many[:ENUM_LIMIT], CLAIMS)
    assert len(defs["UnitRef"]["enum"]) == ENUM_LIMIT
    defs, verifiable, _ = shape(many, [])  # too many refs; no claims
    assert verifiable["cited_units"]["items"] == {"type": "string"} and "UnitRef" not in defs
    assert verifiable["claim_ids"]["maxItems"] == 0 and "ClaimId" not in defs


def test_enum_list_reads_the_limit_when_called(monkeypatch):
    item, field = enum_list("UnitRef", REFS, description="d")
    assert field.description == "d" and issubclass(item.__args__[0], StrEnum)
    assert [m.value for m in item.__args__[0]] == REFS
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 0)
    assert enum_list("UnitRef", REFS)[0] == list[str]


def test_enum_item_is_one_str_enum_or_a_plain_string(monkeypatch):
    item = enum_item("SourceId", ["src1", "src2"])
    assert issubclass(item, StrEnum) and item.__name__ == "SourceId"
    assert [m.value for m in item] == ["src1", "src2"]
    assert enum_item("SourceId", []) is str
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 1)  # read when called
    assert enum_item("SourceId", ["src1", "src2"]) is str


def test_a_draft_that_cites_nothing_allows_no_citations(pack):
    model = audit_output_type(pack, [], [])
    props = model.model_json_schema()["$defs"]["VerifiableFinding"]["properties"]
    assert props["cited_units"]["maxItems"] == 0 and props["claim_ids"]["maxItems"] == 0
    data = _reply(pack)
    model.model_validate(data)  # an empty citation list is fine
    first_verifiable = next(r.id for r in pack.rules if r.checkability is Checkability.VERIFIABLE)
    data["findings"][first_verifiable]["cited_units"] = ["src1"]
    with pytest.raises(ValidationError, match="too_long|at most 0"):
        model.model_validate(data)


def test_a_reply_keyed_by_rule_id_converts_to_audit_output_in_pack_order(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    data = _reply(pack)
    first = pack.rules[0].id
    data["findings"][first] |= {
        "cited_units": ["src1/u2"],
        "claim_ids": ["c1"],
        "recommendation": "r",
    }
    data["findings"] = dict(reversed(list(data["findings"].items())))  # order is not meaning
    data["findings"]["icd203.as.6"] = {"verdict": "pass", "evidence": "x"}  # not a rule: ignored
    out = to_audit_output(model.model_validate_json(json.dumps(data)), pack)
    assert isinstance(out, AuditOutput) and out.summary == "s"
    assert [f.rule_id for f in out.findings] == pack.rule_ids()
    assert all(f.evidence == f"e-{f.rule_id}" for f in out.findings)
    head = out.findings[0]
    assert (head.cited_units, head.claim_ids, head.recommendation) == (["src1/u2"], ["c1"], "r")
    assert type(head.cited_units[0]) is str and type(head.claim_ids[0]) is str  # not enum members
    assert {f.verdict for f in out.findings} == {Verdict.PASS, Verdict.ATTESTED}


def test_an_out_of_enum_value_fails_and_names_the_rule_alias(pack):
    model = audit_output_type(pack, REFS, CLAIMS)
    advisory = next(r.id for r in pack.rules if r.checkability is Checkability.ADVISORY)
    verifiable = next(r.id for r in pack.rules if r.checkability is Checkability.VERIFIABLE)
    data = _reply(pack)
    data["findings"][advisory]["verdict"] = "pass"
    data["findings"][verifiable]["cited_units"] = ["src1"]  # a source id, not a unit
    with pytest.raises(ValidationError) as e:
        model.model_validate_json(json.dumps(data))
    assert {err["loc"] for err in e.value.errors()} == {
        ("findings", advisory, "verdict"),
        ("findings", verifiable, "cited_units", 0),
    }
