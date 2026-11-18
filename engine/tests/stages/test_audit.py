import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import AuditOutput, Finding, FindingOut, Verdict
from corelata.stages import audit_schema
from corelata.stages.audit import (
    ENGINE_CHECK,
    AuditOutcome,
    apply_engine_checks,
    audit_validator,
    auditor_payload,
    merge_engine_findings,
    open_findings,
    run_auditor,
)
from corelata.stages.write import run_writer
from corelata.standards.schema import Checkability
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


async def test_clean_draft_passes(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    findings = (await run_auditor(ctx, iteration=0, draft=draft)).findings
    assert [f.rule_id for f in findings] == ctx.pack.rule_ids()
    assert all(f.iteration == 0 for f in findings)
    assert {f.verdict for f in findings} == {Verdict.PASS, Verdict.ATTESTED}
    assert open_findings(findings) == []
    tc8 = next(f for f in findings if f.rule_id == "icd203.tc.8")
    assert tc8.severity == "blocking" and tc8.route_to == "writer"
    rec = ctx.runner.log.records[-1]
    assert rec.role == "auditor"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    expected = {r for c in draft.claims for r in c.evidence}
    assert {u["ref"] for u in payload["cited_units"]} == expected
    assert "severity" in payload["rules"][0] and "route_to" not in payload["rules"][0]


async def test_run_auditor_sends_the_payload_auditor_payload_builds(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    await run_auditor(ctx, iteration=0, draft=draft)
    rec = ctx.runner.log.records[-1]
    sent = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    cited = sorted({r for c in draft.claims for r in c.evidence})
    units = [{"ref": r, "text": ctx.index.text(r)} for r in cited]
    want = auditor_payload(ctx.pack, draft, units, ctx.value_statement)
    assert sent == json.loads(json.dumps(want))  # the doctor's auditor probe sends this shape


async def test_marked_draft_fails_with_routing(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED BADTERM"))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    findings = (await run_auditor(ctx, iteration=0, draft=draft)).findings
    failed = {f.rule_id for f in open_findings(findings)}
    assert failed == {"icd203.tc.2", "icd203.tc.8", "icd206.src.2", "icd203.as.5"}
    assert all(f.route_to == "writer" for f in open_findings(findings))


def lenient_reply(pack) -> str:
    """An auditor that waives everything: pass verifiable rules, attest advisory ones."""
    findings = {
        r.id: {
            "verdict": "attested" if r.checkability.value == "advisory" else "pass",
            "evidence": "looks fine",
        }
        for r in pack.rules
    }
    return json.dumps({"findings": findings, "summary": "All good."})


async def test_run_auditor_sends_the_by_rule_schema_and_returns_the_same_outcome(
    make_ctx, fake_backend
):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    request = fake_backend.requests[-1]
    assert request.schema_name == "AuditByRule"
    defs = request.json_schema["$defs"]
    assert defs["AuditFindings"]["required"] == ctx.pack.rule_ids()
    cited = sorted({r for c in draft.claims for r in c.evidence})
    assert defs["UnitRef"]["enum"] == cited
    assert defs["ClaimId"]["enum"] == [c.id for c in draft.claims]
    cited_units = defs["VerifiableFinding"]["properties"]["cited_units"]
    assert cited_units["items"] == {"$ref": "#/$defs/UnitRef"}
    assert ctx.runner.log.records[-1].prompt_version == 5
    expected = [
        Finding(
            rule_id=r.id,
            verdict=Verdict.ATTESTED if r.checkability is Checkability.ADVISORY else Verdict.PASS,
            evidence="Synthetic attestation."
            if r.checkability is Checkability.ADVISORY
            else "Synthetic check passed.",
            severity=r.severity.value,
            route_to=r.route_to.value,
            iteration=0,
        )
        for r in ctx.pack.rules
    ]
    assert outcome == AuditOutcome(expected, "Synthetic audit.")


async def test_the_schema_requires_a_finding_for_every_rule(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    reply = json.loads(lenient_reply(ctx.pack))
    del reply["findings"]["icd203.as.1"]
    bad = json.dumps(reply)
    fake_backend.script("auditor", bad, bad)
    with pytest.raises(StructuredOutputError, match=r"findings\.icd203\.as\.1: Field required"):
        await run_auditor(ctx, iteration=0, draft=draft)


async def test_the_schema_rejects_a_verdict_the_rule_does_not_allow(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    reply = json.loads(lenient_reply(ctx.pack))
    reply["findings"]["icd203.tc.8"]["verdict"] = "attested"
    reply["findings"]["zzz.x.1"] = {"verdict": "pass", "evidence": "e"}  # ignored, not an error
    bad = json.dumps(reply)
    fake_backend.script("auditor", bad, lenient_reply(ctx.pack))
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    assert outcome.summary == "All good."
    repair = fake_backend.requests[-1].messages[-1].content
    assert (
        "findings.icd203.tc.8.verdict: Input should be 'pass', 'fail' or 'not_applicable'" in repair
    )
    assert "zzz" not in repair


async def test_engine_overrides_lenient_auditor_on_unsourced_claims(make_ctx, fake_backend):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    ids = [c.id for c in draft.unsourced_claims()]
    assert ids
    data = draft.model_dump()
    data["key_judgments"][0]["claim_ids"].extend(ids)  # link the unsourced claim to a judgment
    draft = type(draft).model_validate(data)
    fake_backend.script("auditor", lenient_reply(ctx.pack))
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    assert outcome.summary == "All good."
    assert len([f for f in outcome.findings if f.rule_id == "icd203.tc.8"]) == 1
    by_rule = {f.rule_id: f for f in outcome.findings}
    tc8 = by_rule["icd203.tc.8"]
    assert tc8.verdict is Verdict.FAIL
    assert tc8.evidence == f"engine check: claims without evidence: {', '.join(ids)}"
    assert tc8.claim_ids == ids
    assert tc8.recommendation == "Cite a source unit for each claim or remove it."
    assert tc8.severity == "blocking" and tc8.route_to == "writer"
    linked = {cid for kj in draft.key_judgments for cid in kj.claim_ids}
    assert linked & set(ids)
    src2 = by_rule["icd206.src.2"]
    assert src2.verdict is Verdict.FAIL and src2.evidence.startswith("engine check:")
    assert {"icd203.tc.8", "icd206.src.2"} <= {f.rule_id for f in open_findings(outcome.findings)}


async def test_engine_override_src2_only_for_key_judgment_claims(make_ctx, fake_backend):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    bad = {c["id"] for c in data["claims"] if not c["evidence"]}
    for kj in data["key_judgments"]:
        kj["claim_ids"] = [c for c in kj["claim_ids"] if c not in bad]
    unlinked = type(draft).model_validate(data)
    fake_backend.script("auditor", lenient_reply(ctx.pack))
    outcome = await run_auditor(ctx, iteration=0, draft=unlinked)
    by_rule = {f.rule_id: f for f in outcome.findings}
    assert by_rule["icd203.tc.8"].verdict is Verdict.FAIL
    assert by_rule["icd206.src.2"].verdict is Verdict.PASS


async def test_engine_check_skips_rules_missing_from_pack(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert draft.unsourced_claims()
    custom = ctx.pack.model_copy(
        update={"rules": [r for r in ctx.pack.rules if r.id != "icd203.tc.8"]}
    )
    assert apply_engine_checks(draft, [], custom) == []


async def test_the_backstop_validator_still_checks_unit_refs(make_ctx, fake_backend, monkeypatch):
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 0)  # every list is "too long": plain strings
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    reply = json.loads(lenient_reply(ctx.pack))
    reply["findings"]["icd203.tc.8"]["cited_units"] = ["src9/u1"]
    bad = json.dumps(reply)
    fake_backend.script("auditor", bad, bad)
    with pytest.raises(StructuredOutputError, match="'src9/u1' is not a unit id"):
        await run_auditor(ctx, iteration=0, draft=draft)


def _legal(pack) -> list[FindingOut]:
    return [
        FindingOut(
            rule_id=r.id,
            verdict=Verdict.ATTESTED if r.checkability is Checkability.ADVISORY else Verdict.PASS,
            evidence="e",
        )
        for r in pack.rules
    ]


def _errors(ctx, findings: list[FindingOut]) -> list[str]:
    return audit_validator(ctx)(AuditOutput(findings=findings, summary="s"))


def _swap(findings: list[FindingOut], rule_id: str, **update) -> list[FindingOut]:
    return [f.model_copy(update=update) if f.rule_id == rule_id else f for f in findings]


def test_validator_accepts_one_legal_finding_per_rule(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _legal(ctx.pack)) == []


def test_validator_tells_the_model_the_verdicts_an_advisory_rule_takes(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _swap(_legal(ctx.pack), "icd203.as.1", verdict=Verdict.PASS)) == [
        "rule 'icd203.as.1' is advisory: set its verdict to 'attested' (or 'not_applicable'), "
        "not 'pass'"
    ]


def test_validator_tells_the_model_the_verdicts_a_verifiable_rule_takes(make_ctx):
    ctx = make_ctx()
    assert _errors(ctx, _swap(_legal(ctx.pack), "icd203.tc.8", verdict=Verdict.ATTESTED)) == [
        "rule 'icd203.tc.8' is verifiable: set its verdict to 'pass', 'fail' or "
        "'not_applicable', not 'attested'"
    ]


def test_validator_lists_the_rule_ids_for_an_unknown_rule(make_ctx):
    ctx = make_ctx()
    extra = FindingOut(rule_id="icd203.as.6", verdict=Verdict.ATTESTED, evidence="e")
    assert _errors(ctx, [*_legal(ctx.pack), extra]) == [
        "'icd203.as.6' is not a rule in this pack; the rule ids are: "
        + ", ".join(ctx.pack.rule_ids())
    ]


def test_validator_asks_for_exactly_one_finding_and_names_a_missing_one(make_ctx):
    ctx = make_ctx()
    legal = _legal(ctx.pack)
    twice = next(f for f in legal if f.rule_id == "icd203.tc.8")
    assert _errors(ctx, [*legal, twice]) == ["give exactly one finding for rule 'icd203.tc.8'"]
    missing = [f for f in legal if f.rule_id != "icd203.as.1"]
    assert _errors(ctx, missing) == ["missing a finding for rule 'icd203.as.1'"]


def test_validator_names_real_unit_ids_for_a_bad_ref(make_ctx):
    ctx = make_ctx()
    found = _swap(_legal(ctx.pack), "icd203.tc.8", cited_units=["src1"])
    assert _errors(ctx, found) == [
        "'src1' is not a unit id; cite unit ids exactly as given in the input, such as "
        "src1/u1, src1/u2, src1/u3"
    ]


def _finding(rule_id: str, iteration: int, evidence: str, verdict=Verdict.FAIL) -> Finding:
    return Finding(
        rule_id=rule_id,
        verdict=verdict,
        evidence=evidence,
        severity="major",
        route_to="writer",
        iteration=iteration,
    )


def test_merge_engine_findings_drops_a_stale_engine_check_and_keeps_the_auditors_own():
    # iteration 0: the engine failed tc.8 and src.2, the auditor itself failed tc.3 and passed
    # tc.1; iteration 1's audit degraded and the engine now fails only src.2 (CRL-30)
    previous = [
        _finding("icd203.tc.8", 0, f"{ENGINE_CHECK}claims without evidence: c99"),
        _finding("icd206.src.2", 0, f"{ENGINE_CHECK}claims without evidence: c99"),
        _finding("icd203.tc.3", 0, "no analytic line"),
        _finding("icd203.tc.1", 0, "looks fine", Verdict.PASS),
    ]
    engine = [_finding("icd206.src.2", 1, f"{ENGINE_CHECK}claims without evidence: c0")]
    merged = merge_engine_findings(previous, engine)
    assert [f.id for f in merged] == ["icd203.tc.3@0", "icd203.tc.1@0", "icd206.src.2@1"]
    assert [f.id for f in open_findings(merged)] == ["icd203.tc.3@0", "icd206.src.2@1"]


def test_merge_engine_findings_replaces_a_rule_the_engine_still_fails_without_duplicating_it():
    previous = [_finding("icd203.tc.8", 0, f"{ENGINE_CHECK}claims without evidence: c99")]
    engine = [_finding("icd203.tc.8", 1, f"{ENGINE_CHECK}claims without evidence: c99")]
    assert [f.id for f in merge_engine_findings(previous, engine)] == ["icd203.tc.8@1"]


def test_merge_engine_findings_with_nothing_before_is_the_engines_findings():
    engine = [_finding("icd203.tc.8", 0, f"{ENGINE_CHECK}claims without evidence: c99")]
    assert merge_engine_findings([], engine) == engine
    assert merge_engine_findings([], []) == []


async def test_the_auditor_sees_which_cited_units_ocr_read(make_ctx):
    """CRL-95: icd203.tc.1 can weigh a passage read from a scan."""
    source = text_source("src1", *PORT)
    units = [
        u.model_copy(update={"meta": {"ocr": True, "ocr_confidence": 64.0}}) for u in source.units
    ]
    ctx = make_ctx(source.model_copy(update={"units": units}))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    await run_auditor(ctx, iteration=0, draft=draft)
    rec = ctx.runner.log.records[-1]
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert payload["cited_units"]
    assert all(u["ocr"] is True and u["ocr_confidence"] == 64.0 for u in payload["cited_units"])
