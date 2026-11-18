import json

import pytest

from corelata.schema import ReportStatus, RunState
from corelata.testing.sources import coglossa_source, text_source
from corelata.trace import (
    TraceError,
    claim_provenance,
    delivered_open_findings,
    draft_changes,
    format_summary,
    load_record,
    run_trace,
    summarize,
)
from tests.stages.conftest import PORT


async def test_summarize_clean_run(run):
    rec = await run(run_id="r1")
    s = summarize(rec)
    assert s.run_id == "r1" and s.state is RunState.COMPLETED and s.status is ReportStatus.CLEAN
    assert s.iterations == 0 and s.max_iterations == 2
    assert s.pack_name == "icd203-base" and s.pack_hash == rec.pack_hash and s.profile is None
    assert [x.model_dump() for x in s.sources] == [
        {
            "id": "src1",
            "name": "src1.txt",
            "kind": "file",
            "format": "txt",
            "sha256": rec.sources[0].sha256,
            "units": 3,
            "digested": False,
            "coglossa_run_id": None,
            "reliability_tier": None,
            "ocr_pages": 0,
        }
    ]
    assert len(s.sources[0].sha256) == 64
    assert s.gate is not None and s.gate.supported
    assert [(x.stage, x.iteration, x.ok, x.duration_ms) for x in s.stages] == [
        ("ingesting", 0, True, 0),
        ("gating", 0, True, 0),
        ("drafting", 0, True, 0),
        ("conveying", 0, True, 0),
        ("auditing", 0, True, 0),
        ("rendering", 0, True, 0),
    ]
    assert len(s.findings) == 1
    it0 = s.findings[0]
    assert it0.iteration == 0 and it0.failed == [] and it0.open == []
    assert it0.passed == 12 and it0.attested == 5 and it0.not_applicable == 0
    assert s.open_findings == [] and s.usage.calls == 4
    assert s.prompt_versions["writer"] == 5 and s.error is None


async def test_summary_shows_a_coglossa_sources_reliability_tier(run):
    """CRL-96: the Sources tab and `corelata trace` show the tier."""
    rec = await run(text_source("src1", *PORT), coglossa_source("src2", "A", "B"))
    s = summarize(rec)
    assert [x.reliability_tier for x in s.sources] == [None, "B"]
    assert "  src2 report.json (coglossa, 2 units, Coglossa run run-42, reliability tier B)" in (
        format_summary(s)
    )
    assert rec.report is not None
    assert rec.report.sources[1].reliability_note.startswith("Coglossa reliability tier B.")


async def test_summarize_findings_loop_and_open_at_delivery(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED UNFIXABLE detail on Varna."))
    s = summarize(rec)
    assert s.status is ReportStatus.FINDINGS_OPEN and s.iterations == 2
    assert [f.iteration for f in s.findings] == [0, 1, 2]
    assert s.findings[0].failed == ["icd203.as.5", "icd203.tc.8", "icd206.src.2"]
    assert s.findings[0].open == ["icd203.as.5@0", "icd203.tc.8@0", "icd206.src.2@0"]
    assert [f.id for f in s.open_findings] == ["icd203.as.5@2", "icd203.tc.8@2", "icd206.src.2@2"]
    assert [f.id for f in delivered_open_findings(rec)] == [f.id for f in s.open_findings]
    text = format_summary(s)
    assert text.splitlines()[0] == (
        f"run {rec.run_id}: completed findings_open after 2 revision(s) (max 2)"
    )
    assert "  iteration 0: failed icd203.as.5, icd203.tc.8, icd206.src.2" in text
    assert "open at delivery:" in text and "icd203.tc.8@2 (blocking)" in text
    assert "usage: 10 calls" in text


async def test_summarize_gate_rejected_and_failed_runs(run, fake_backend):
    rejected = summarize(await run(statement="Lunar helium mining"))
    assert rejected.state is RunState.GATE_REJECTED and rejected.status is None
    assert rejected.findings == [] and rejected.open_findings == []
    assert delivered_open_findings(await run(statement="Lunar helium mining")) == []
    text = format_summary(rejected)
    assert text.splitlines()[0].endswith(": gate_rejected")
    assert "gate: not supported, insufficient" in text

    from corelata.llm.types import PermanentBackendError

    fake_backend.script("writer", PermanentBackendError("down"), PermanentBackendError("down"))
    failed = summarize(await run())
    assert failed.state is RunState.FAILED and "down" in failed.error
    assert [x.ok for x in failed.stages if x.stage == "drafting"] == [False, False]
    assert "drafting" in format_summary(failed) and "FAIL" in format_summary(failed)


async def test_claim_provenance(run):
    rec = await run(text_source("src1", *PORT), text_source("src2", "Rail links to Varna."))
    prov = claim_provenance(rec, "c0")
    assert prov.claim.id == "c0" and prov.claim.kind.value == "judgment"
    assert [e.model_dump() for e in prov.evidence] == [
        {
            "ref": "src1/u1",
            "source_id": "src1",
            "source_name": "src1.txt",
            "locator": "para 1",
            "text": PORT[0],
        }
    ]
    assert prov.cited_by == ["key_judgments[0]", "analysis[0].paragraphs[0]"]
    with pytest.raises(TraceError, match="unknown claim id 'zzz'"):
        claim_provenance(rec, "zzz")
    with pytest.raises(TraceError, match="has no report"):
        claim_provenance(await run(statement="Lunar helium mining"), "c0")


async def test_draft_changes_between_iterations(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    conveyed = [d.report for d in rec.drafts if d.role == "conveyor"]
    assert len(conveyed) == 2
    changes = draft_changes(conveyed[0], conveyed[1])
    assert changes.claims_removed == ["c99"] and changes.claims_added == []
    assert changes.claims_reworded == [] and not changes.title_changed
    assert not changes.key_judgments_changed and changes.sections_changed == ["Analysis"]
    reworded = conveyed[1].model_copy(
        update={
            "title": "New",
            "claims": [
                c.model_copy(update={"text": c.text + "!"}) if c.id == "c1" else c
                for c in conveyed[1].claims
            ],
        }
    )
    again = draft_changes(conveyed[1], reworded)
    assert again.title_changed and again.claims_reworded == ["c1"]
    assert again.sections_changed == []


async def test_load_record_roundtrip_and_errors(run, tmp_path):
    rec = await run(run_id="r9")
    (tmp_path / "trace.json").write_text(json.dumps(rec.model_dump(mode="json")))
    assert load_record(tmp_path).run_id == "r9"
    with pytest.raises(TraceError, match="no trace.json in"):
        load_record(tmp_path / "nowhere")
    (tmp_path / "trace.json").write_text("{not json")
    with pytest.raises(TraceError, match="trace.json is not valid JSON"):
        load_record(tmp_path)
    (tmp_path / "trace.json").write_text(json.dumps({"schema_version": "1", "run_id": "x"}))
    with pytest.raises(TraceError, match="trace.json is not a Corelata run record"):
        load_record(tmp_path)


async def test_run_trace_shows_draft_changes_and_calls_without_bodies(run):
    rec = await run(run_id="r1")
    view = run_trace(rec)
    assert view.summary == summarize(rec)
    assert [(d.role, d.iteration) for d in view.drafts] == [("writer", 0), ("conveyor", 0)]
    assert view.drafts[0].changes is None
    assert view.drafts[1].changes is not None and view.drafts[1].changes.title_changed
    assert [c.role for c in view.calls] == ["gate", "writer", "conveyor", "auditor"]
    assert all(c.ok for c in view.calls)
    assert "request" not in view.calls[0].model_dump() and "response" not in view.model_dump()
    assert rec.llm_calls[0].request is not None  # the record keeps the bodies; the view drops them


async def test_format_summary_prints_each_degradation(run, fake_backend):
    fake_backend.script("auditor", *["not JSON"] * 4)
    rec = await run()
    [line] = rec.report.metadata.degradations
    text = format_summary(summarize(rec), [line])
    assert f"degraded: {line}" in text.splitlines()
    assert "degraded:" not in format_summary(summarize(await run()))


async def test_summary_counts_the_pages_ocr_read(run):
    """CRL-95: the Sources tab and `corelata trace` say a source's text came from a scan."""
    source = text_source("src1", *PORT).model_copy(update={"provenance": {"ocr_pages": [1, 4]}})
    s = summarize(await run(source))
    assert s.sources[0].ocr_pages == 2
    assert "  src1 src1.txt (txt, 3 units, text recovered by OCR (2 pages))" in format_summary(s)


async def test_the_summary_lists_the_earlier_reports_the_run_was_given(run, make_config):
    """CRL-97: the summary (the Process tab) and `corelata trace` name them, the cut ones
    marked; a run without them has no such key or line."""
    from datetime import UTC, datetime

    from corelata.schema import PriorJudgment, PriorReport

    given = [
        PriorReport(
            run_id=rid,
            title=f"Report {rid}",
            accepted_at=datetime(2026, 11, day, tzinfo=UTC),
            key_judgments=[PriorJudgment(text="x" * size, confidence="low")],
        )
        for rid, day, size in (("r-a", 14, 10), ("r-b", 13, 9000))
    ]
    cfg = make_config(pipeline={"prior_judgments": {"max_reports": 3}})
    s = summarize(await run(cfg=cfg, prior_reports=given))
    assert [(p.run_id, p.cut) for p in s.prior_reports] == [("r-a", False), ("r-b", True)]
    lines = format_summary(s).splitlines()
    at = lines.index("earlier accepted reports:")
    assert lines[at + 1 : at + 3] == [
        "  r-a 2026-11-14 Report r-a",
        "  r-b 2026-11-13 Report r-b (cut: over the token budget)",
    ]
    plain = summarize(await run())
    assert "prior_reports" not in plain.model_dump()
    assert "earlier accepted reports:" not in format_summary(plain)
