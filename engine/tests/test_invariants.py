"""Property tests for the spec §8.4 invariants, run against the validators, not a model."""

from hypothesis import given, settings
from hypothesis import strategies as st

from corelata.ingest.units import UnitIndex
from corelata.schema import (
    AuditOutput,
    Claim,
    ClaimKind,
    Finding,
    FindingOut,
    ReportBody,
    Verdict,
)
from corelata.stages.audit import apply_engine_checks, audit_validator
from corelata.stages.context import StageContext
from corelata.stages.write import report_validator
from corelata.standards.loader import load_pack
from corelata.standards.schema import Checkability
from corelata.testing.sources import text_source
from corelata.testing.synthetic import synthetic_response
from tests.conftest import build_config
from tests.stages.conftest import PORT

SETTINGS = settings(max_examples=50, deadline=None)
PACK = load_pack("icd203-base")
SOURCES = [text_source("src1", *PORT)]
REFS = ["src1/u1", "src1/u2", "src1/u3"]


def _ctx() -> StageContext:
    return StageContext(
        cfg=build_config(),
        runner=None,  # type: ignore[arg-type]  # validators never call the model
        pack=PACK,
        sources=SOURCES,
        index=UnitIndex.from_sources(SOURCES),
        value_statement="Varna port capacity",
    )


def _valid_body() -> dict:
    ctx = _ctx()
    payload = {
        "task": "writer",
        "value_statement": ctx.value_statement,
        "template": {},
        "rules": [],
        "lexicon": PACK.lexicon.model_dump(),
        "digests": [],
        "units": ctx.unit_payload(ctx.index.refs()),
        "sources": ctx.source_payload(),
        "prior_draft": None,
        "findings": [],
        "extra_guidance": "",
        "iteration": 0,
    }
    return synthetic_response(payload)


BASE = _valid_body()


def _bare(claims: list[dict]) -> ReportBody:
    """A valid body whose claims are replaced; no references to them remain."""
    data = {**BASE, "claims": claims, "key_judgments": [], "analysis": [], "alternatives": []}
    return ReportBody.model_validate(data)


@st.composite
def bodies_with_unsourced(draw) -> ReportBody:
    sourced = draw(st.lists(st.lists(st.sampled_from(REFS), max_size=3, unique=True), max_size=4))
    kinds = st.sampled_from(ClaimKind)
    evidence = [*sourced, []]
    claims = [
        Claim(id=f"k{i}", text="t", kind=draw(kinds), evidence=ev).model_dump()
        for i, ev in enumerate(evidence)
    ]
    return _bare(claims)


def _finding(rule_id: str, verdict: Verdict) -> Finding:
    rule = PACK.rule(rule_id)
    return Finding(
        **FindingOut(rule_id=rule_id, verdict=verdict, evidence="e").model_dump(),
        severity=rule.severity.value,
        route_to=rule.route_to.value,
        iteration=0,
    )


@SETTINGS
@given(
    body=bodies_with_unsourced(),
    verdict=st.sampled_from([Verdict.PASS, Verdict.NOT_APPLICABLE, Verdict.FAIL]),
)
def test_invariant_1_unsourced_claims_always_fail_tc8(body, verdict):
    out = apply_engine_checks(body, [_finding("icd203.tc.8", verdict)], PACK)
    assert len(out) == 1 and out[0].verdict is Verdict.FAIL
    if verdict is not Verdict.FAIL:
        expected = [c.id for c in body.unsourced_claims()]
        assert out[0].claim_ids == expected
        assert out[0].evidence == f"engine check: claims without evidence: {', '.join(expected)}"


def _legal(rule_id: str, verdict: Verdict) -> bool:
    if PACK.rule(rule_id).checkability is Checkability.VERIFIABLE:
        return verdict is not Verdict.ATTESTED
    return verdict not in (Verdict.PASS, Verdict.FAIL)


@st.composite
def audit_outputs(draw) -> AuditOutput:
    findings = []
    for rid in PACK.rule_ids():
        for _ in range(draw(st.sampled_from([0, 1, 1, 1, 2]))):
            verdict = draw(st.sampled_from(Verdict))
            findings.append(FindingOut(rule_id=rid, verdict=verdict, evidence="e"))
    return AuditOutput(findings=findings, summary="s")


@SETTINGS
@given(out=audit_outputs())
def test_invariant_2_one_finding_per_rule_with_legal_verdict(out):
    errors = audit_validator(_ctx())(out)
    by_rule: dict[str, list[FindingOut]] = {}
    for f in out.findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    expected_ok = all(
        len(by_rule.get(rid, [])) == 1 and _legal(rid, by_rule[rid][0].verdict)
        for rid in PACK.rule_ids()
    )
    assert (errors == []) is expected_ok


@SETTINGS
@given(term=st.one_of(st.text(max_size=20), st.sampled_from(sorted(PACK.lexicon.terms()))))
def test_invariant_3_likelihood_term_accepted_iff_in_lexicon(term):
    claim = {**BASE["claims"][0], "likelihood_term": term}
    errors = [e for e in report_validator(_ctx())(_bare([claim])) if "likelihood term" in e]
    assert (errors == []) is (term in PACK.lexicon.terms())
