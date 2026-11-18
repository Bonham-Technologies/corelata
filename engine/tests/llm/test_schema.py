import json

from pydantic import BaseModel, Field

from corelata.llm.schema import strict_json_schema
from corelata.schema import DigestOutput, DiscoveryResult, GateVerdict, ProfileDraft, ReportBody
from corelata.stages.audit_schema import audit_output_type
from corelata.stages.report_schema import report_output_type
from corelata.standards.loader import load_pack

REFS = ["src1/u1", "src1/u2", "src2/u1"]
STATIC = [GateVerdict, DiscoveryResult, ReportBody, DigestOutput, ProfileDraft]


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


def _schemas():
    out = [m.model_json_schema() for m in STATIC]
    pack = load_pack("icd203-base")
    out.append(audit_output_type(pack, REFS, ["c0"]).model_json_schema())
    out.append(audit_output_type(pack, [], []).model_json_schema())
    out.append(report_output_type(REFS, ["src1", "src2"]).model_json_schema())
    out.append(report_output_type([], ["src1"]).model_json_schema())
    return out


def _check_no_default(node):
    if isinstance(node, dict):
        assert "default" not in node
        for k, v in node.items():
            if k == "properties":
                for sub in v.values():
                    _check_no_default(sub)
            else:
                _check_no_default(v)
    elif isinstance(node, list):
        for v in node:
            _check_no_default(v)


def test_every_real_schema_is_strict_and_default_free():
    for schema in _schemas():
        strict = strict_json_schema(schema)
        for node in _nodes(strict):
            if isinstance(node.get("properties"), dict):
                assert node["additionalProperties"] is False
                assert node["required"] == list(node["properties"])
        _check_no_default(strict)


def test_defs_refs_enums_and_max_items_are_preserved():
    pack = load_pack("icd203-base")
    full = audit_output_type(pack, REFS, ["c0"]).model_json_schema()
    empty = audit_output_type(pack, [], []).model_json_schema()
    for original in (full, empty):
        strict = strict_json_schema(original)
        assert set(strict["$defs"]) == set(original["$defs"])
        refs = [n["$ref"] for n in _nodes(original) if "$ref" in n]
        assert refs == [n["$ref"] for n in _nodes(strict) if "$ref" in n]
    strict = strict_json_schema(full)
    assert strict["$defs"]["UnitRef"] == {"enum": REFS, "title": "UnitRef", "type": "string"}
    cited_full = strict["$defs"]["VerifiableFinding"]["properties"]["cited_units"]
    assert cited_full["items"] == {"$ref": "#/$defs/UnitRef"}
    strict_empty = strict_json_schema(empty)
    cited = strict_empty["$defs"]["VerifiableFinding"]["properties"]["cited_units"]
    assert cited["maxItems"] == 0


def test_idempotent_and_does_not_mutate():
    for schema in _schemas():
        before = json.dumps(schema, sort_keys=True)
        once = strict_json_schema(schema)
        assert json.dumps(schema, sort_keys=True) == before
        assert strict_json_schema(once) == once


def test_property_named_default_survives():
    class M(BaseModel):
        default_: int = Field(default=3, alias="default")
        other: str | None = None

    strict = strict_json_schema(M.model_json_schema(by_alias=True))
    assert list(strict["properties"]) == ["default", "other"]
    assert strict["required"] == ["default", "other"]
    assert "default" not in strict["properties"]["default"]


def test_bare_object_and_non_dict_nodes():
    assert strict_json_schema({"type": "object"}) == {
        "type": "object",
        "additionalProperties": False,
    }
    assert strict_json_schema({"type": "object", "additionalProperties": True}) == {
        "type": "object",
        "additionalProperties": True,
    }


def test_full_document_still_validates_with_the_original_model():
    strict = strict_json_schema(GateVerdict.model_json_schema())
    doc = {
        "supported": True,
        "substance": "thin",
        "reasons": ["r"],
        "evidence": ["src1/u1"],
        "suggested_scope": "narrow",
    }
    assert list(doc) == strict["required"]
    assert GateVerdict.model_validate(doc).evidence == ["src1/u1"]


def test_profile_draft_with_explicit_nulls_and_empty_lists_validates():
    strict = strict_json_schema(ProfileDraft.model_json_schema())
    doc = {
        "observations": ["o"],
        "tone": "t",
        "key_judgments": None,
        "analysis_max_words": None,
        "heading_style": "plain",
        "handling_markings": [],
        "source_descriptors": [],
        "disable": [],
        "override": [],
    }
    assert list(doc) == strict["required"]
    assert ProfileDraft.model_validate(doc).key_judgments is None
