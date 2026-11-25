"""CRL-97: the writer and the auditor read the key judgments of the project's earlier accepted
reports, and `icd203.tc.7` is checked against them; in-process runs against the fake backend."""

import json
from datetime import UTC, datetime

import pytest

from corelata.exports import render_outputs
from corelata.llm.payload import parse_input
from corelata.render.outline import SECTION_TITLES
from corelata.schema import (
    PriorJudgment,
    PriorReport,
    ReportStatus,
    RunState,
    Verdict,
)
from corelata.stages.audit import INITIAL_COVERAGE
from corelata.standards.loader import load_pack
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT

TC7 = "icd203.tc.7"
# Project memory is off unless configured (an upgraded install keeps its behaviour); these
# tests turn it on as the example config does.
ON = {"prior_judgments": {"max_reports": 3, "budget_tokens": 2000}}


def prior(run_id: str, day: int, *judgments: str, title: str = "Varna capacity") -> PriorReport:
    return PriorReport(
        run_id=run_id,
        title=title,
        accepted_at=datetime(2026, 11, day, 9, tzinfo=UTC),
        key_judgments=[
            PriorJudgment(text=j, confidence="moderate") for j in judgments or ["Varna grows."]
        ],
    )


def requests_by_task(fake_backend) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in fake_backend.requests:
        task = parse_input([m.model_dump() for m in r.messages])["task"]
        out.setdefault(task, []).append(r)
    return out


def payload(request) -> dict:
    return parse_input([m.model_dump() for m in request.messages])


def finding(rec, rule_id: str, iteration: int = 0):
    return next(f for f in rec.findings if f.rule_id == rule_id and f.iteration == iteration)


def sent(fake_backend) -> list[dict]:
    """Every request, as the server would see it."""
    return [r.model_dump() for r in fake_backend.requests]


async def test_one_accepted_report_reaches_the_writer_and_the_auditor_checks_tc7(
    run, fake_backend, make_config
):
    """AC1: the writer's request carries the earlier report's key judgments and asks for
    `changes_from_previous`; the auditor checks tc.7 as verifiable and passes it."""
    earlier = prior("r-earlier", 12, "Varna's capacity will keep growing.")
    rec = await run(cfg=make_config(pipeline=ON), prior_reports=[earlier])
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.CLEAN
    by_task = requests_by_task(fake_backend)
    writer = by_task["writer"][0]
    assert payload(writer)["prior_reports"] == [
        {
            "run_id": "r-earlier",
            "title": "Varna capacity",
            "date": "2026-11-12",
            "key_judgments": [
                {"text": "Varna's capacity will keep growing.", "confidence": "moderate"}
            ],
        }
    ]
    assert "INPUT_JSON.prior_reports" in writer.messages[0].content
    assert writer.json_schema["$defs"]["PriorRunId"]["enum"] == ["r-earlier"]
    auditor = by_task["auditor"][0]
    assert payload(auditor)["prior_reports"] == payload(writer)["prior_reports"]
    assert "INPUT_JSON.prior_reports" in auditor.messages[0].content
    sent_tc7 = next(r for r in payload(auditor)["rules"] if r["id"] == TC7)
    assert sent_tc7["checkability"] == "verifiable"
    assert sent_tc7["evidence_required"].startswith("INPUT_JSON.prior_reports")
    tc7_schema = auditor.json_schema["$defs"]["AuditFindings"]["properties"][TC7]
    assert tc7_schema == {"$ref": "#/$defs/VerifiableFinding"}
    assert finding(rec, TC7).verdict is Verdict.PASS
    # the report says how it stands against the earlier one, and the renders show it
    [change] = rec.report.changes_from_previous
    assert change.prior_run_id == "r-earlier" and change.change.value == "consistent"
    assert change.prior_judgment == "Varna's capacity will keep growing."
    assert [r.run_id for r in rec.report.metadata.prior_reports] == ["r-earlier"]
    assert [(p.run_id, p.cut) for p in rec.prior_reports] == [("r-earlier", False)]
    # the snapshot is the pack as written: the block is in it, the run's checkability is not
    snapshot_tc7 = next(r for r in rec.pack_snapshot["rules"] if r["id"] == TC7)
    assert snapshot_tc7["checkability"] == "advisory" and "with_prior_reports" in snapshot_tc7
    files = render_outputs(rec, load_pack("icd203-base"), with_claim_ids=False)
    title = SECTION_TITLES["changes_from_previous"]
    for name in ("report.md", "report.html"):
        text = files[name]
        assert title in text and "12 November 2026" in text and "r-earlier" not in text
    assert "## Key judgments" in files["report.md"]
    md = files["report.md"]
    assert md.index("## Key judgments") < md.index(title) < md.index("## Scope note")
    assert json.loads(files["trace.json"])["prior_reports"][0]["run_id"] == "r-earlier"


async def test_a_report_silent_on_the_earlier_judgments_fails_tc7(run, fake_backend, make_config):
    """AC1: the auditor fails tc.7 when the draft says nothing about the earlier judgments; a
    minor failure, so the report is still delivered clean and the writer is not looped."""
    rec = await run(
        text_source("src1", *PORT, "NOCHANGES in the Varna port."),
        cfg=make_config(pipeline=ON),
        prior_reports=[prior("r-earlier", 12)],
    )
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.CLEAN
    tc7 = finding(rec, TC7)
    assert tc7.verdict is Verdict.FAIL and tc7.severity == "minor"
    assert rec.report.changes_from_previous == []
    assert "changes_from_previous" not in rec.report.model_dump()


async def test_a_project_without_accepted_reports_is_initial_coverage(
    run, fake_backend, make_config
):
    """AC1: with project memory and no accepted report, tc.7 is `not_applicable`; every request
    is the one a run without project memory sends (only tc.7's verdict differs)."""
    without = await run(run_id="r1")
    requests = sent(fake_backend)
    fake_backend.requests = []
    rec = await run(run_id="r1", cfg=make_config(pipeline=ON), prior_reports=[])
    assert sent(fake_backend) == requests
    tc7 = finding(rec, TC7)
    assert tc7.verdict is Verdict.NOT_APPLICABLE and tc7.evidence == INITIAL_COVERAGE
    assert finding(without, TC7).verdict is Verdict.ATTESTED
    assert [f for f in rec.findings if f.rule_id != TC7] == [
        f for f in without.findings if f.rule_id != TC7
    ]
    assert rec.prior_reports == [] and "prior_reports" not in rec.model_dump()
    assert "prior_reports" not in rec.report.metadata.model_dump()


@pytest.mark.parametrize("found", [None, [], "one"])
@pytest.mark.parametrize("off", [{"max_reports": 0}, None])
async def test_max_reports_zero_sends_todays_requests(run, fake_backend, make_config, found, off):
    """AC5: `max_reports: 0`, or `prior_judgments` unset (an upgraded install's config), reads
    nothing, whatever the host found: tc.7 is attested as before (never initial coverage), the
    requests are those of a run without project memory, the trace has no `prior_reports`."""
    baseline = await run(run_id="r1")
    requests = sent(fake_backend)
    fake_backend.requests = []
    cfg = make_config(pipeline={} if off is None else {"prior_judgments": off})
    assert cfg.pipeline.prior_judgments.max_reports == 0
    given = [prior("r-earlier", 12)] if found == "one" else found
    rec = await run(run_id="r1", cfg=cfg, prior_reports=given)
    assert sent(fake_backend) == requests
    assert finding(rec, TC7).verdict is Verdict.ATTESTED
    assert rec.findings == baseline.findings
    assert "prior_reports" not in rec.model_dump() and rec.report == baseline.report


async def test_the_budget_drops_the_oldest_reports_and_the_trace_names_them(
    run, fake_backend, make_config
):
    """AC3: newest first while they fit `budget_tokens`; the first that does not fit and every
    older one are cut, and the trace marks them."""
    reports = [
        prior("r-new", 14, "A newer judgment."),
        prior("r-mid", 13, "x" * 2000),  # does not fit what the newest leaves
        prior("r-old", 12, "An old judgment."),  # would fit, but older reports go first
        prior("r-oldest", 11),  # beyond max_reports: never given
    ]
    cfg = make_config(pipeline={"prior_judgments": {"max_reports": 3, "budget_tokens": 300}})
    rec = await run(cfg=cfg, prior_reports=reports)
    assert [(p.run_id, p.cut) for p in rec.prior_reports] == [
        ("r-new", False),
        ("r-mid", True),
        ("r-old", True),
    ]
    writer = requests_by_task(fake_backend)["writer"][0]
    assert [p["run_id"] for p in payload(writer)["prior_reports"]] == ["r-new"]
    assert writer.json_schema["$defs"]["PriorRunId"]["enum"] == ["r-new"]
    assert [r.run_id for r in rec.report.metadata.prior_reports] == ["r-new"]
    assert finding(rec, TC7).verdict is Verdict.PASS


async def test_reports_all_cut_leave_tc7_as_written(run, fake_backend, make_config):
    """Earlier reports exist but none fit: the run cannot check tc.7, and it is not initial
    coverage either, so the rule is read as written and nothing about them is sent."""
    await run(run_id="r1")
    requests = sent(fake_backend)
    fake_backend.requests = []
    cfg = make_config(pipeline={"prior_judgments": {"max_reports": 3, "budget_tokens": 100}})
    rec = await run(run_id="r1", cfg=cfg, prior_reports=[prior("r-big", 12, "y" * 2000)])
    assert sent(fake_backend) == requests
    assert finding(rec, TC7).verdict is Verdict.ATTESTED
    assert [(p.run_id, p.cut) for p in rec.prior_reports] == [("r-big", True)]


async def test_a_pack_without_the_block_keeps_tc7_advisory_with_earlier_reports(
    run, fake_backend, tmp_path
):
    """An install whose pack predates CRL-97 (the pack directory is never overwritten on
    upgrade): the writer still reads the earlier reports, tc.7 stays advisory and is attested,
    and an empty project is not called initial coverage."""
    import shutil

    from corelata.standards.loader import BUILTIN_PACKS_DIR

    packs = tmp_path / "packs"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", packs / "icd203-base")
    rule = packs / "icd203-base" / "rules" / "icd203.tc.7.yaml"
    text = rule.read_text()
    rule.write_text(text[: text.index("with_prior_reports:")])
    pack = load_pack("icd203-base", packs_dir=packs)
    assert pack.prior_report_rules() == []
    from corelata.llm.agent import CallLog
    from corelata.pipeline import RunOptions, run_report
    from corelata.prompts.library import PromptLibrary
    from tests.conftest import build_config

    async def go(given):
        return await run_report(
            build_config(pipeline=ON),
            [text_source("src1", *PORT)],
            RunOptions(
                value_statement="Varna port capacity expansion matters to shippers",
                prior_reports=given,
            ),
            backends={"fake": fake_backend},
            prompts=PromptLibrary(),
            log=CallLog(),
            pack=pack,
        )

    rec = await go([prior("r-earlier", 12)])
    assert finding(rec, TC7).verdict is Verdict.ATTESTED
    assert len(rec.report.changes_from_previous) == 1
    assert finding(await go([]), TC7).verdict is Verdict.ATTESTED


async def test_a_source_ocr_read_and_earlier_reports_reach_the_writer_and_the_auditor_together(
    run, fake_backend, make_config
):
    """CRL-95 with CRL-97: a scanned source's units keep their OCR flag while the writer and the
    auditor also read the project's earlier judgments, and both prompts explain both."""
    ocr = {"ocr": True, "ocr_confidence": 64.0}
    source = text_source("src1", *PORT)
    scanned = source.model_copy(
        update={
            "units": [u.model_copy(update={"meta": ocr}) for u in source.units],
            "provenance": {"ocr_pages": [1], "ocr_languages": ["eng"]},
        }
    )
    earlier = prior("r-earlier", 12, "Varna's capacity will keep growing.")
    rec = await run(scanned, cfg=make_config(pipeline=ON), prior_reports=[earlier])
    assert rec.state is RunState.COMPLETED and finding(rec, TC7).verdict is Verdict.PASS
    by_task = requests_by_task(fake_backend)
    writer, auditor = by_task["writer"][0], by_task["auditor"][0]
    assert all(u | ocr == u for u in payload(writer)["units"])
    cited = payload(auditor)["cited_units"]
    assert cited and all(u | ocr == u for u in cited)
    for request in (writer, auditor):
        system = request.messages[0].content
        assert '"ocr": true' in system and "INPUT_JSON.prior_reports" in system
        assert [p["run_id"] for p in payload(request)["prior_reports"]] == ["r-earlier"]
    versions = {(c.role, c.prompt_version) for c in rec.llm_calls}
    assert {("writer", 6), ("auditor", 6)} <= versions
