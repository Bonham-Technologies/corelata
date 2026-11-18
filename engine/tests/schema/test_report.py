import pytest
from pydantic import ValidationError

from corelata.schema import (
    Alternative,
    Claim,
    ClaimKind,
    Confidence,
    DiscoveryResult,
    Finding,
    FindingOut,
    KeyJudgment,
    Paragraph,
    Report,
    ReportBody,
    ReportMetadata,
    Section,
    SourceEntry,
    Verdict,
)


def body(**overrides) -> ReportBody:
    data = dict(
        title="T",
        handling_marking="UNCLASSIFIED",
        key_judgments=[KeyJudgment(text="KJ", confidence=Confidence.MODERATE, claim_ids=["c1"])],
        scope_note="scope",
        sources=[SourceEntry(source_id="src1", descriptor="open-source report")],
        analysis=[Section(heading="A", paragraphs=[Paragraph(text="p", claim_ids=["c1"])])],
        alternatives=[Alternative(hypothesis="h", assessment="a")],
        gaps_and_indicators=["gap"],
        claims=[Claim(id="c1", text="claim", kind=ClaimKind.JUDGMENT, evidence=["src1/u1"])],
    )
    data.update(overrides)
    return ReportBody(**data)


def test_valid_body():
    b = body()
    assert b.referenced_claim_ids() == {"c1"}
    assert b.unsourced_claims() == []


def test_unknown_claim_id_rejected():
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        body(key_judgments=[KeyJudgment(text="x", confidence=Confidence.LOW, claim_ids=["c9"])])


def test_duplicate_claim_ids_rejected():
    claims = [
        Claim(id="c1", text="a", kind=ClaimKind.FACT, evidence=["src1/u1"]),
        Claim(id="c1", text="b", kind=ClaimKind.FACT, evidence=["src1/u1"]),
    ]
    with pytest.raises(ValidationError, match="duplicate claim id 'c1'"):
        body(claims=claims)


def test_unsourced_claims_listed():
    b = body(claims=[Claim(id="c1", text="x", kind=ClaimKind.FACT, evidence=[])])
    assert [c.id for c in b.unsourced_claims()] == ["c1"]


def test_report_wraps_body_with_metadata():
    r = Report(**body().model_dump(), metadata=ReportMetadata(pack_name="p", pack_hash="h"))
    assert r.metadata.iteration == 0 and r.metadata.status is None


def test_discovery_max_five():
    cands = [{"text": f"c{i}", "audience": "a", "evidence": ["src1/u1"]} for i in range(6)]
    with pytest.raises(ValidationError):
        DiscoveryResult(candidates=cands)


def test_finding_id_and_output_has_no_report_field():
    f = Finding(
        **FindingOut(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="e").model_dump(),
        severity="blocking",
        route_to="writer",
        iteration=1,
    )
    assert f.id == "icd203.tc.8@1"
    assert "report" not in FindingOut.model_fields and "report" not in Finding.model_fields


def test_metadata_degradations_default_to_empty_and_older_reports_load():
    older = ReportMetadata.model_validate({"pack_name": "p", "pack_hash": "h", "status": "clean"})
    assert older.degradations == []
    m = ReportMetadata(pack_name="p", pack_hash="h", degradations=["audit incomplete: x"])
    assert m.model_dump(mode="json")["degradations"] == ["audit incomplete: x"]
