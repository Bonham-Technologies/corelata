from corelata.quotes import quote_found
from corelata.schema import (
    AuditOutput,
    DigestOutput,
    DiscoveryResult,
    GateVerdict,
    ProfileDraft,
    ReportBody,
)
from corelata.testing.synthetic import key_terms, synthetic_response

UNITS = [
    {
        "ref": "src1/u1",
        "text": "The port of Varna expanded its container capacity in 2025.",
        "locator": "para 1",
        "source": "a.txt",
    },
    {
        "ref": "src1/u2",
        "text": "Capacity expansion was financed by a state bank.",
        "locator": "para 2",
        "source": "a.txt",
    },
    {
        "ref": "src2/u1",
        "text": "Container traffic through Varna rose 40 percent.",
        "locator": "para 1",
        "source": "b.txt",
    },
]
LEXICON = {
    "likelihood": [{"term": "likely", "low": 55, "high": 80}],
    "confidence_definitions": {"high": "h", "moderate": "m", "low": "l"},
    "source_descriptors": ["open-source report"],
    "handling_markings": ["UNCLASSIFIED"],
}
SOURCES = [
    {"id": "src1", "name": "a.txt", "format": "txt", "provenance": {}},
    {"id": "src2", "name": "b.txt", "format": "txt", "provenance": {}},
]
RULES = [
    {"id": "icd203.tc.2", "checkability": "verifiable", "severity": "blocking"},
    {"id": "icd203.tc.8", "checkability": "verifiable", "severity": "blocking"},
    {"id": "icd203.as.1", "checkability": "advisory", "severity": "major"},
    {"id": "icd203.as.5", "checkability": "verifiable", "severity": "major"},
]


def extra_unit(text):
    return {"ref": "src2/u2", "text": text, "locator": "p", "source": "b"}


def writer_payload(units=UNITS, findings=None):
    return {
        "task": "writer",
        "value_statement": "Varna port capacity expansion matters to shippers",
        "template": {},
        "rules": [],
        "lexicon": LEXICON,
        "digests": [],
        "units": units,
        "sources": SOURCES,
        "prior_draft": None,
        "findings": findings or [],
        "extra_guidance": "",
        "iteration": 1 if findings else 0,
    }


def audit_payload(draft):
    return {
        "task": "auditor",
        "draft": draft,
        "rules": RULES,
        "lexicon": LEXICON,
        "cited_units": [],
        "value_statement": "v",
    }


def test_key_terms():
    assert key_terms("The Port of Varna, the port!") == ["port", "varna"]


def test_gate_supported_and_thin_vs_sufficient():
    statement = "Varna container capacity"
    v = GateVerdict.model_validate(
        synthetic_response(
            {"task": "gate", "value_statement": statement, "digests": [], "units": UNITS}
        )
    )
    assert v.supported and v.substance.value == "sufficient" and v.evidence[0] == "src1/u1"
    v2 = GateVerdict.model_validate(
        synthetic_response(
            {"task": "gate", "value_statement": statement, "digests": [], "units": UNITS[:1]}
        )
    )
    assert v2.supported and v2.substance.value == "thin" and v2.suggested_scope
    v3 = GateVerdict.model_validate(
        synthetic_response(
            {"task": "gate", "value_statement": "lunar mining", "digests": [], "units": UNITS}
        )
    )
    assert not v3.supported and v3.substance.value == "insufficient"


def test_discover_one_candidate_per_source():
    r = DiscoveryResult.model_validate(
        synthetic_response(
            {"task": "discover", "audience_hint": "ops", "digests": [], "units": UNITS}
        )
    )
    assert len(r.candidates) == 2 and r.candidates[0].audience == "ops"


def test_digest_groups_by_five():
    units = [{"ref": f"src1/u{i}", "text": f"t{i}"} for i in range(1, 12)]
    d = DigestOutput.model_validate(
        synthetic_response(
            {"task": "digest", "source": {"id": "src1", "name": "x"}, "units": units}
        )
    )
    assert [len(s.unit_refs) for s in d.sections] == [5, 5, 1]


def test_writer_valid_and_markers():
    body = ReportBody.model_validate(synthetic_response(writer_payload()))
    assert body.unsourced_claims() == [] and body.handling_marking == "UNCLASSIFIED"
    marked = [*UNITS, extra_unit("UNSOURCED BADTERM here")]
    body = ReportBody.model_validate(synthetic_response(writer_payload(marked)))
    assert [c.id for c in body.unsourced_claims()] == ["c99"]
    assert "BADTERM" in body.key_judgments[0].text
    fixed = ReportBody.model_validate(
        synthetic_response(writer_payload(marked, findings=[{"rule_id": "x"}]))
    )
    assert fixed.unsourced_claims() == [] and "BADTERM" not in fixed.key_judgments[0].text
    stubborn = [*UNITS, extra_unit("UNSOURCED UNFIXABLE")]
    still = ReportBody.model_validate(
        synthetic_response(writer_payload(stubborn, findings=[{"rule_id": "x"}]))
    )
    assert [c.id for c in still.unsourced_claims()] == ["c99"]


def test_writer_quotes_its_units_and_borrows_a_statement_quotation_until_findings():
    plain = synthetic_response(writer_payload())
    assert all("quotes" not in c for c in plain["claims"])  # no evidence_quotes: no quotes
    payload = {**writer_payload(), "evidence_quotes": "required"}
    body = ReportBody.model_validate(synthetic_response(payload))
    texts = {u["ref"]: u["text"] for u in UNITS}
    for c in body.claims:
        assert [q.ref for q in c.quotes] == c.evidence
        assert all(quote_found(q.text, texts[q.ref]) for q in c.quotes)
    said = 'The harbour master said the port "will close to all tankers by March"'
    borrowed = ReportBody.model_validate(synthetic_response({**payload, "value_statement": said}))
    assert borrowed.claims[0].quotes[0].text == "will close to all tankers by March"
    assert borrowed.claims[1].quotes == body.claims[1].quotes
    fixed = ReportBody.model_validate(
        synthetic_response({**payload, "value_statement": said, "findings": [{"rule_id": "x"}]})
    )
    assert quote_found(fixed.claims[0].quotes[0].text, texts[fixed.claims[0].evidence[0]])


def test_conveyor_prefixes_once():
    draft = synthetic_response(writer_payload())
    once = synthetic_response({"task": "conveyor", "draft": draft})
    twice = synthetic_response({"task": "conveyor", "draft": once})
    assert once["title"].startswith("Conveyed: ") and twice["title"] == once["title"]


def _audit(draft) -> AuditOutput:
    raw = synthetic_response(audit_payload(draft))
    assert list(raw["findings"]) == [r["id"] for r in RULES]  # keyed by rule id, in order
    findings = [{"rule_id": rid, **f} for rid, f in raw["findings"].items()]
    return AuditOutput.model_validate({"findings": findings, "summary": raw["summary"]})


def test_auditor_one_finding_per_rule():
    draft = synthetic_response(writer_payload([*UNITS, extra_unit("UNSOURCED BADTERM")]))
    verdicts = {f.rule_id: f.verdict.value for f in _audit(draft).findings}
    assert verdicts == {
        "icd203.tc.2": "fail",
        "icd203.tc.8": "fail",
        "icd203.as.1": "attested",
        "icd203.as.5": "fail",
    }
    clean = synthetic_response(writer_payload())
    assert {f.verdict.value for f in _audit(clean).findings} == {"pass", "attested"}


PACK = {
    "name": "icd203-base",
    "version": "1",
    "rule_ids": ["icd203.tc.4", "icd203.tc.9"],
    "rules": [],
    "template": {},
    "lexicon": {
        "handling_markings": ["UNCLASSIFIED"],
        "source_descriptors": [],
        "likelihood_terms": [],
    },
}


def _reports(*units: str, n: int = 3):
    return [{"name": f"r{i}.md", "units": list(units), "truncated": False} for i in range(n)]


def test_profiler_plain_reports():
    out = synthetic_response({"task": "profiler", "pack": PACK, "reports": _reports("Varna grew.")})
    draft = ProfileDraft.model_validate(out)
    assert draft.observations == ["3 example reports read", "3 passages in total"]
    assert draft.tone.startswith("Lead with the key judgments")
    assert draft.heading_style == "plain" and draft.key_judgments is None
    assert draft.handling_markings == [] and draft.disable == [] and draft.override == []


def test_profiler_markers_steer_the_draft():
    out = synthetic_response(
        {
            "task": "profiler",
            "pack": PACK,
            "reports": _reports(
                "UNCLASSIFIED//FOUO",
                "1. Key Judgments",
                "BLUF: ports matter.",
                "A CHART shows traffic.",
                "NOALT",
                "UNCLASSIFIED//FOUO",
                n=1,
            ),
        }
    )
    draft = ProfileDraft.model_validate(out)
    assert draft.handling_markings == ["UNCLASSIFIED//FOUO"]
    assert draft.heading_style == "numbered"
    assert draft.key_judgments is not None and draft.key_judgments.max == 3
    assert draft.tone.endswith("Open with a bottom line up front.")
    assert [o.model_dump() for o in draft.override] == [{"id": "icd203.tc.9", "severity": "major"}]
    assert draft.disable == ["icd203.tc.4"]


def test_profiler_badrule_marker_proposes_an_unknown_rule():
    out = synthetic_response(
        {"task": "profiler", "pack": PACK, "reports": _reports("BADRULE", n=1)}
    )
    assert out["disable"] == ["nope.rule.1"]
