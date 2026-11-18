import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from corelata.llm.schema import strict_json_schema
from corelata.schema import ReportBody, ReportBodyWithChanges
from corelata.stages.audit_schema import ENUM_LIMIT
from corelata.stages.report_schema import report_output_type

REFS = ["src1/u1", "src1/u2", "src2/u1"]
SOURCES = ["src1", "src2"]


def _body(evidence: list[str], source_id: str = "src1") -> dict:
    return {
        "title": "t",
        "handling_marking": "UNCLASSIFIED",
        "key_judgments": [{"text": "k", "confidence": "moderate", "claim_ids": ["c1"]}],
        "scope_note": "s",
        "sources": [{"source_id": source_id, "descriptor": "open-source report"}],
        "analysis": [{"heading": "h", "paragraphs": [{"text": "p", "claim_ids": ["c1"]}]}],
        "alternatives": [],
        "gaps_and_indicators": [],
        "claims": [{"id": "c1", "text": "t", "kind": "fact", "evidence": evidence}],
    }


GOLDEN_OFF = Path(__file__).parent / "golden" / "report-body-quotes-off.json"


ACCESS = ["direct", "indirect", "unknown"]


def test_the_schema_is_report_body_with_one_enum_each_for_unit_refs_and_source_ids():
    model = report_output_type(REFS, SOURCES, quotes=True, access_terms=ACCESS, summary=True)
    assert model.__name__ == "ReportBody"  # the schema name the server sees
    want = ReportBody.model_json_schema()
    del want["properties"]["changes_from_previous"]  # no earlier reports
    del want["$defs"]["JudgmentChange"], want["$defs"]["ChangeKind"]
    want["$defs"]["Claim"]["properties"]["evidence"]["items"] = {"$ref": "#/$defs/UnitRef"}
    want["$defs"]["UnitRef"] = {"enum": REFS, "title": "UnitRef", "type": "string"}
    want["$defs"]["Quote"]["properties"]["ref"] = {"$ref": "#/$defs/UnitRef"}
    want["$defs"]["SourceEntry"]["properties"]["source_id"] = {"$ref": "#/$defs/SourceId"}
    want["$defs"]["SourceEntry"]["properties"]["access"] = {"$ref": "#/$defs/SourceAccess"}
    want["$defs"]["SourceEntry"]["required"].append("access")
    want["$defs"]["SourceId"] = {"enum": SOURCES, "title": "SourceId", "type": "string"}
    want["$defs"]["SourceAccess"] = {"enum": ACCESS, "title": "SourceAccess", "type": "string"}
    summary = want["$defs"]["SourceSummaryStatement"]["properties"]
    for name in ("key_sources", "conflicting_sources"):
        summary[name]["items"] = {"$ref": "#/$defs/SourceId"}
    want["properties"]["source_summary"] = {"$ref": "#/$defs/SourceSummaryStatement"}
    want["required"].append("source_summary")
    got = model.model_json_schema()
    assert got == want  # same fields, descriptions and required lists; three new defs
    fields = [f for f in ReportBody.model_fields if f != "changes_from_previous"]
    assert list(got["properties"]) == fields  # field order kept
    entry = got["$defs"]["SourceEntry"]["properties"]
    assert list(entry) == [
        "source_id",
        "descriptor",
        "reliability_note",
        "date_of_information",
        "origin",
        "access",
    ]
    assert json.dumps(got).count('"src2"') == 1  # the source ids are emitted once
    assert list(got["$defs"]["Claim"]["properties"])[-1] == "quotes"


def test_without_source_details_or_summary_the_schema_is_the_one_sent_before_them():
    """CRL-96: a pack whose lexicon has no `source_access` and whose template has no
    `source_summary` section sends the schema of the release before."""
    quoting = report_output_type(REFS, SOURCES, quotes=True).model_json_schema()
    assert list(quoting["$defs"]["SourceEntry"]["properties"]) == [
        "source_id",
        "descriptor",
        "reliability_note",
    ]
    assert "source_summary" not in quoting["properties"]
    assert "SourceSummaryStatement" not in quoting["$defs"]
    only_summary = report_output_type(REFS, SOURCES, summary=True).model_json_schema()
    assert "access" not in only_summary["$defs"]["SourceEntry"]["properties"]
    assert only_summary["required"][-1] == "source_summary"
    only_details = report_output_type(REFS, SOURCES, access_terms=ACCESS).model_json_schema()
    assert "source_summary" not in only_details["properties"]


def test_source_details_and_summary_are_inside_the_strict_subset():
    model = report_output_type(REFS, SOURCES, access_terms=ACCESS, summary=True)
    strict = strict_json_schema(model.model_json_schema())
    entry = strict["$defs"]["SourceEntry"]
    assert entry["required"] == list(entry["properties"]) and not entry["additionalProperties"]
    summary = strict["$defs"]["SourceSummaryStatement"]
    assert summary["required"] == [
        "strengths_and_weaknesses",
        "key_sources",
        "corroboration",
        "conflicting_sources",
    ]
    assert summary["additionalProperties"] is False
    assert strict["required"][-1] == "source_summary"
    assert "default" not in json.dumps(strict)


def test_access_and_summary_sources_are_enums():
    model = report_output_type(REFS, SOURCES, access_terms=ACCESS, summary=True)
    data = _body(["src1/u1"])
    data["sources"][0]["access"] = "telepathic"
    data["source_summary"] = {
        "strengths_and_weaknesses": "s",
        "key_sources": ["src9"],
        "corroboration": "c",
        "conflicting_sources": ["src1", "src2"],
    }
    with pytest.raises(ValidationError) as e:
        model.model_validate(data)
    locs = {err["loc"] for err in e.value.errors()}
    assert locs == {("sources", 0, "access"), ("source_summary", "key_sources", 0)}
    data["sources"][0]["access"] = "direct"
    data["source_summary"]["key_sources"] = ["src1"]
    body = ReportBody.model_validate(model.model_validate(data).model_dump())
    assert body.source_summary is not None and body.source_summary.conflicting_sources == SOURCES
    assert body.sources[0].access == "direct"


def test_without_quotes_the_schema_is_the_one_sent_before_quotes_existed():
    """CRL-93: `evidence_quotes: off` sends byte for byte the schema of the release before; the
    golden file was generated from that release's `report_output_type(REFS, SOURCES)`."""
    got = report_output_type(REFS, SOURCES).model_json_schema()
    assert json.dumps(got, indent=2) + "\n" == GOLDEN_OFF.read_text()
    assert "quotes" not in json.dumps(got) and "Quote" not in got["$defs"]


def test_the_quote_schema_is_inside_the_strict_subset():
    strict = strict_json_schema(report_output_type(REFS, SOURCES, quotes=True).model_json_schema())
    quote = strict["$defs"]["Quote"]
    assert quote["required"] == ["ref", "text"] and quote["additionalProperties"] is False
    claim = strict["$defs"]["Claim"]
    assert claim["required"][-1] == "quotes" and claim["additionalProperties"] is False

    def refs_alone(node: object) -> None:  # OpenAI refuses keywords beside a $ref
        if isinstance(node, dict):
            assert "$ref" not in node or len(node) == 1, node
            for v in node.values():
                refs_alone(v)
        elif isinstance(node, list):
            for v in node:
                refs_alone(v)

    refs_alone(strict)


def test_a_quote_names_a_unit_of_the_run():
    model = report_output_type(REFS, SOURCES, quotes=True)
    data = _body(["src1/u1"])
    data["claims"][0]["quotes"] = [{"ref": "src9/u1", "text": "words"}]
    with pytest.raises(ValidationError) as e:
        model.model_validate(data)
    [err] = e.value.errors()
    assert err["loc"] == ("claims", 0, "quotes", 0, "ref") and err["type"] == "enum"
    data["claims"][0]["quotes"] = [{"ref": "src1/u1", "text": "words"}]
    model.model_validate(data)
    none = report_output_type([], SOURCES, quotes=True).model_json_schema()
    assert none["$defs"]["Claim"]["properties"]["quotes"]["maxItems"] == 0
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(many, SOURCES, quotes=True).model_json_schema()
    assert above["$defs"]["Quote"]["properties"]["ref"] == {"title": "Ref", "type": "string"}


def test_evidence_is_plain_strings_above_the_limit_and_empty_without_refs():
    many = [f"src1/u{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(many, SOURCES).model_json_schema()
    assert above["$defs"]["Claim"]["properties"]["evidence"]["items"] == {"type": "string"}
    assert "UnitRef" not in above["$defs"]
    at_limit = report_output_type(many[:ENUM_LIMIT], SOURCES).model_json_schema()
    assert len(at_limit["$defs"]["UnitRef"]["enum"]) == ENUM_LIMIT
    none = report_output_type([], SOURCES)
    claim = none.model_json_schema()["$defs"]["Claim"]["properties"]["evidence"]
    assert claim["maxItems"] == 0
    none.model_validate(_body([]))
    with pytest.raises(ValidationError, match="too_long|at most 0"):
        none.model_validate(_body(["src1/u1"]))


def test_source_ids_are_a_plain_string_above_the_limit():
    many = [f"src{i}" for i in range(1, ENUM_LIMIT + 2)]
    above = report_output_type(REFS, many).model_json_schema()
    source_id = above["$defs"]["SourceEntry"]["properties"]["source_id"]
    assert source_id == {"title": "Source Id", "type": "string"}
    assert "SourceId" not in above["$defs"]
    at_limit = report_output_type(REFS, many[:ENUM_LIMIT]).model_json_schema()
    assert len(at_limit["$defs"]["SourceId"]["enum"]) == ENUM_LIMIT
    report_output_type(REFS, many).model_validate(_body(["src1/u1"], source_id="src9"))


def test_a_source_id_or_an_invented_ref_is_not_a_unit():
    model = report_output_type(REFS, SOURCES)
    for bad in ("src1", "src9/u1"):
        with pytest.raises(ValidationError) as e:
            model.model_validate_json(json.dumps(_body([bad])))
        [err] = e.value.errors()
        assert err["loc"] == ("claims", 0, "evidence", 0) and err["type"] == "enum", bad


def test_an_invented_source_id_is_not_a_source():
    model = report_output_type(REFS, SOURCES)
    for bad in ("src9", "src1/u1"):
        with pytest.raises(ValidationError) as e:
            model.model_validate_json(json.dumps(_body(["src1/u1"], source_id=bad)))
        [err] = e.value.errors()
        assert err["loc"] == ("sources", 0, "source_id") and err["type"] == "enum", bad


def test_the_claim_id_validator_still_runs_on_the_per_call_type():
    data = _body(["src1/u1"])
    data["key_judgments"][0]["claim_ids"] = ["c9"]
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        report_output_type(REFS, SOURCES).model_validate(data)


PRIOR = ["r-new", "r-old"]


def test_with_earlier_reports_the_schema_adds_changes_naming_them():
    """CRL-97: the writer that read earlier accepted reports may only name their run ids, one
    `PriorRunId` enum; the rest of the schema is the one without them."""
    without = report_output_type(REFS, SOURCES).model_json_schema()
    got = report_output_type(REFS, SOURCES, prior_run_ids=PRIOR).model_json_schema()
    assert list(got["properties"]) == list(ReportBodyWithChanges.model_fields)
    assert list(got["properties"])[-1] == "changes_from_previous"
    changes = got["properties"].pop("changes_from_previous")
    assert changes["items"] == {"$ref": "#/$defs/JudgmentChange"}
    change = got["$defs"].pop("JudgmentChange")
    assert change["properties"]["prior_run_id"] == {"$ref": "#/$defs/PriorRunId"}
    assert change["properties"]["change"] == {"$ref": "#/$defs/ChangeKind"}
    assert got["$defs"].pop("PriorRunId") == {
        "enum": PRIOR,
        "title": "PriorRunId",
        "type": "string",
    }
    assert got["$defs"].pop("ChangeKind")["enum"] == ["consistent", "changed"]
    assert got == without


def test_with_earlier_reports_and_a_source_summary_the_schema_has_both():
    """CRL-96 with CRL-97: each adds its own field; the body keeps `ReportBody`'s field order."""
    got = report_output_type(
        REFS, SOURCES, prior_run_ids=PRIOR, access_terms=["unknown"], summary=True
    ).model_json_schema()
    assert list(got["properties"]) == list(ReportBody.model_fields)
    assert got["properties"]["source_summary"] == {"$ref": "#/$defs/SourceSummaryStatement"}
    assert "PriorRunId" in got["$defs"] and "SourceAccess" in got["$defs"]
    strict_json_schema(got)


def test_the_changes_schema_is_inside_the_strict_subset():
    strict = strict_json_schema(
        report_output_type(REFS, SOURCES, quotes=True, prior_run_ids=PRIOR).model_json_schema()
    )
    change = strict["$defs"]["JudgmentChange"]
    assert change["required"] == [
        "prior_run_id",
        "prior_judgment",
        "change",
        "explanation",
        "claim_ids",
    ]
    assert change["additionalProperties"] is False
    assert strict["required"][-1] == "changes_from_previous"

    def refs_alone(node: object) -> None:  # OpenAI refuses keywords beside a $ref
        if isinstance(node, dict):
            assert "$ref" not in node or len(node) == 1, node
            for v in node.values():
                refs_alone(v)
        elif isinstance(node, list):
            for v in node:
                refs_alone(v)

    refs_alone(strict)


def test_a_reply_with_changes_parses_as_the_canonical_body_and_claim_ids_resolve():
    body = _body(["src1/u1"])
    body["changes_from_previous"] = [
        {
            "prior_run_id": "r-new",
            "prior_judgment": "Capacity will grow.",
            "change": "changed",
            "explanation": "The financing stalled.",
            "claim_ids": ["c9"],
        }
    ]
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        ReportBody.model_validate(body)
    body["changes_from_previous"][0]["claim_ids"] = ["c1"]
    parsed = ReportBody.model_validate(body)
    assert parsed.changes_from_previous[0].change.value == "changed"
    assert "changes_from_previous" in parsed.model_dump()
    assert "changes_from_previous" not in ReportBody.model_validate(_body(["src1/u1"])).model_dump()
