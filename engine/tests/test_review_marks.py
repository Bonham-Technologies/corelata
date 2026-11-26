"""Review marks (CRL-139): a reviewer marks claims checked or disputed; a return hands the disputed
ones to the rerun's writer as findings; a profile may require the key-judgment claims checked
before Accept; and "How this report was produced" ends the renders when the profile asks."""

import asyncio
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from docx import Document

from corelata import service
from corelata.exports import dump_json, render_outputs
from corelata.render.outline import PRODUCTION_TITLE
from corelata.render.production import names, production_lines
from corelata.schema import (
    REVIEW_FINDING_RULE,
    Claim,
    ClaimKind,
    ClaimMark,
    KeyJudgment,
    LLMCallRecord,
    Report,
    ReviewAction,
    ReviewMark,
    RunRecord,
    RunState,
    Usage,
    Verdict,
)
from corelata.schema.review import (
    accept_blockers,
    checked_by,
    disputed_findings,
    key_judgment_claims,
    marks_view,
)
from corelata.standards.loader import pack_hash
from corelata.store import records, runs
from tests.render.fixtures import PACK, SOURCES, make_report
from tests.test_prior_reports import payload, requests_by_task
from tests.test_service import Svc, _set_state

T0 = datetime(2026, 11, 26, 9, tzinfo=UTC)


def _report() -> Report:
    """Three claims; the key judgments rest on c1 and c2."""
    r = make_report(status="clean")
    return r.model_copy(
        update={
            "key_judgments": [
                KeyJudgment(text="Capacity grew.", confidence="moderate", claim_ids=["c1", "c2"]),
                KeyJudgment(text="It will grow.", confidence="low", claim_ids=["c2"]),
            ],
            "claims": [
                Claim(id="c1", text="Grew.", kind=ClaimKind.FACT, evidence=["src1/u1"]),
                Claim(id="c2", text="Will grow.", kind=ClaimKind.JUDGMENT, evidence=["src1/u1"]),
                Claim(id="c3", text="Shippers care.", kind=ClaimKind.FACT, evidence=[]),
            ],
        }
    )


def _mark(claim: str, mark: str, minutes: int, actor: str | None = "ana", comment: str = ""):
    return ReviewMark(
        claim_id=claim,
        mark=ClaimMark(mark),
        comment=comment,
        actor=actor,
        at=T0 + timedelta(minutes=minutes),
    )


# ---------------------------------------------------------------- pure rules


def test_a_claims_latest_mark_is_its_mark_and_the_view_counts_them():
    marks = [
        _mark("c1", "disputed", 0, "bob"),
        _mark("c2", "checked", 1, "ana"),
        _mark("c1", "checked", 2, "cy"),
        _mark("c9", "disputed", 3),  # not a claim of the report: ignored
        _mark("c3", "disputed", 4, comment="no source"),
    ]
    view = marks_view(_report(), marks, editable=True, require_key_judgments_checked=False)
    assert [(m.claim_id, m.mark, m.actor) for m in view.marks] == [
        ("c1", "checked", "cy"),
        ("c2", "checked", "ana"),
        ("c3", "disputed", "ana"),
    ]
    assert (view.claims, view.checked, view.disputed) == (3, 2, 1)
    assert view.reviewers == ["ana", "cy"]  # bob's mark on c1 was replaced
    assert view.key_judgment_claim_ids == ["c1", "c2"]
    assert view.editable and not view.require_key_judgments_checked


def test_checked_by_skips_marks_without_an_actor():
    marks = [_mark("c1", "checked", 0, None), _mark("c2", "checked", 1, "ana")]
    assert checked_by(marks, {"c1", "c2"}) == ["ana"]


def test_accept_blockers_name_unchecked_key_judgment_claims_and_disputed_claims():
    report = _report()
    assert key_judgment_claims(report) == ["c1", "c2"]
    assert accept_blockers(report, []) == ["key-judgment claims not checked: c1, c2"]
    marks = [_mark("c1", "checked", 0), _mark("c2", "disputed", 1), _mark("c3", "disputed", 2)]
    assert accept_blockers(report, marks) == [
        "key-judgment claims not checked: c2",
        "claims disputed: c2, c3",
    ]
    done = [_mark("c1", "checked", 0), _mark("c2", "checked", 1)]
    assert accept_blockers(report, done) == []


def test_each_disputed_claim_becomes_one_writer_finding():
    marks = [
        _mark("c3", "disputed", 0, comment="  Which shippers?  "),
        _mark("c1", "disputed", 1, comment="Wrong year"),
        _mark("c1", "checked", 2),  # undisputed again
        _mark("c2", "disputed", 3),
    ]
    found = disputed_findings(_report(), marks)
    assert [(f.claim_ids, f.recommendation) for f in found] == [
        (["c2"], ""),
        (["c3"], "Which shippers?"),
    ]
    first = found[0]
    assert first.rule_id == REVIEW_FINDING_RULE and first.verdict is Verdict.FAIL
    assert (first.route_to, first.severity, first.iteration) == ("writer", "major", 0)
    assert first.evidence == "The reviewer disputed claim c2: “Will grow.”"
    assert first.cited_units == ["src1/u1"]


# ---------------------------------------------------------------- the production statement


def _record(**overrides) -> RunRecord:
    calls = [
        LLMCallRecord(
            role=role, backend="b", model=model, prompt_id=role, prompt_version=1, attempt=1, ok=ok
        )
        for role, model, ok in [
            ("auditor", "m-audit", True),
            ("writer", "m-write", True),
            ("writer", "m-write", True),
            ("writer", "m-big", True),
            ("gate", "m-gate", True),
            ("conveyor", "m-broken", False),  # a failed call used no model's output
            ("zeta", "m-z", True),  # a role this version does not order comes last
        ]
    ]
    data = {
        "corelata_version": "0",
        "run_id": "r1",
        "created_at": T0,
        "value_statement": "v",
        "pack_name": "icd203-base",
        "pack_hash": "0123456789abcdef",
        "pack_snapshot": {},
        "config_hash": "c",
        "prompt_versions": {},
        "max_iterations": 2,
        "iterations": 1,
        "usage": Usage(calls=0, tokens_in=0, tokens_out=0, by_role={}),
        "llm_calls": calls,
        "sources": SOURCES,
        "report": _report(),
        **overrides,
    }
    return RunRecord(**data)


ON = PACK.model_copy(
    update={
        "format": PACK.format.model_copy(update={"production_statement": True}),
        "profile": "team-east",
    }
)


def test_the_production_statement_is_off_by_default_and_needs_a_report():
    assert PACK.format.production_statement is False
    assert production_lines(_record(), PACK) is None
    assert production_lines(_record(report=None), ON) is None


def test_the_production_statement_lines():
    marks = [_mark("c1", "checked", 0, "ana"), _mark("c2", "checked", 1, "bob")]
    assert production_lines(_record(review_marks=marks), ON) == [
        "Models: gate m-gate; writer m-write, m-big; auditor m-audit; zeta m-z.",
        "Standards pack: icd203-base 1.2.0, profile team-east (hash 0123456789abcdef).",
        "Audit: no findings open at delivery after 1 revision.",
        "Review: 2 of 3 claims checked by ana and bob.",
    ]


def test_the_production_statement_counts_open_findings_degradations_and_disputes():
    report = _report()
    meta = report.metadata.model_copy(
        update={"open_findings": ["a@1", "b@1"], "degradations": ["audit incomplete"]}
    )
    record = _record(
        report=report.model_copy(update={"metadata": meta}),
        llm_calls=[],
        iterations=0,
        review_marks=[_mark("c3", "disputed", 0)],
    )
    plain = PACK.model_copy(update={"format": ON.format})  # no profile
    assert production_lines(record, plain) == [
        "Models: none recorded.",
        "Standards pack: icd203-base 1.2.0 (hash 0123456789abcdef).",
        "Audit: 2 findings open at delivery; 1 stage incomplete after 0 revisions.",
        "Review: 0 of 3 claims checked; 1 disputed.",
    ]


def test_names_reads_as_a_list():
    assert [names([]), names(["a"]), names(["a", "b"]), names(["a", "b", "c"])] == [
        "",
        "a",
        "a and b",
        "a, b and c",
    ]


def test_renders_are_unchanged_byte_for_byte_with_the_setting_off():
    """Criterion 4: off by default, and off renders exactly what a render without the setting
    renders; the pack's dump and hash are unchanged too."""
    record = _record(review_marks=[_mark("c1", "checked", 0)])
    off = PACK.model_copy(
        update={"format": PACK.format.model_copy(update={"production_statement": False})}
    )
    assert pack_hash(off) == pack_hash(PACK)
    assert "production_statement" not in json.dumps(off.model_dump(mode="json"))
    assert "review" not in off.model_dump(mode="json")
    before = render_outputs(
        record.model_copy(update={"review_marks": []}), PACK, with_claim_ids=False
    )
    after = render_outputs(record, off, with_claim_ids=False)
    for name in ("report.md", "report.html", "report.docx", "report.json"):
        assert before[name] == after[name], name
    assert PRODUCTION_TITLE not in str(after["report.md"])


def test_md_html_and_docx_end_with_the_section_when_the_profile_asks():
    record = _record(review_marks=[_mark("c1", "checked", 0, "ana")])
    out = render_outputs(record, ON, with_claim_ids=False)
    md, html = str(out["report.md"]), str(out["report.html"])
    review = "Review: 1 of 3 claims checked by ana."
    assert f"## {PRODUCTION_TITLE}\n\n- Models: gate m-gate" in md
    assert md.index(PRODUCTION_TITLE) > md.index("## Gaps")
    assert md.rstrip().endswith(f"- {review}\n\nUNCLASSIFIED")
    assert f'<section class="appendix">\n<h2>{PRODUCTION_TITLE}</h2>' in html
    assert '<ul class="production">' in html and review in html
    assert isinstance(out["report.docx"], bytes)
    paragraphs = [p.text for p in Document(io.BytesIO(out["report.docx"])).paragraphs]
    at = paragraphs.index(PRODUCTION_TITLE)
    assert review in paragraphs[at + 1 :][-1]


# ---------------------------------------------------------------- the writer


async def test_a_reruns_first_writer_call_reads_the_disputed_claims(run, fake_backend):
    findings = disputed_findings(_report(), [_mark("c2", "disputed", 0, comment="Too sure")])
    rec = await run(reviewer_findings=findings, max_iterations=1)
    assert rec.state is RunState.COMPLETED
    first = requests_by_task(fake_backend)["writer"][0]
    assert [f["claim_ids"] for f in payload(first)["findings"]] == [["c2"]]
    assert payload(first)["findings"][0]["recommendation"] == "Too sure"
    assert "the reviewer's findings on the previous version" in first.messages[0].content
    assert rec.reviewer_findings == findings
    assert rec.prompt_versions["writer"] == 7
    dumped = json.loads(dump_json(rec.model_dump(mode="json")))
    assert dumped["reviewer_findings"][0]["claim_ids"] == ["c2"]


async def test_a_run_without_disputed_claims_writes_as_before(run, fake_backend):
    rec = await run()
    first = requests_by_task(fake_backend)["writer"][0]
    assert payload(first)["findings"] == []
    assert "reviewer's findings" not in first.messages[0].content
    dumped = rec.model_dump(mode="json")
    assert "reviewer_findings" not in dumped and "review_marks" not in dumped


# ---------------------------------------------------------------- the service


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _delivered(svc: Svc, *, require: bool = False, production: bool = False) -> uuid.UUID:
    """A completed run whose delivered report is `_report()`, its profile's review settings set."""
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    async with svc.db.session() as s, s.begin():
        row = await runs.get_run(s, run_id, lock=True)
        row.report = _report().model_dump(mode="json")
        snapshot = dict(row.pack_snapshot)
        if require:
            snapshot["review"] = {"require_key_judgments_checked": True}
        if production:
            snapshot["format"] = {**snapshot["format"], "production_statement": True}
        row.pack_snapshot = snapshot
    return run_id


def _review(svc: Svc, run_id: uuid.UUID, action: ReviewAction, **kw):
    return service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, action, **kw
    )


async def test_marks_persist_with_actor_and_time_and_reach_the_record(svc):
    run_id = await _delivered(svc)
    view = await service.mark_claim(svc.db, run_id, "c1", ClaimMark.DISPUTED, actor="bob")
    assert (view.checked, view.disputed, view.editable) == (0, 1, True)
    view = await service.mark_claim(
        svc.db, run_id, "c1", ClaimMark.CHECKED, comment="  matches para 1 ", actor="ana"
    )
    assert [(m.claim_id, m.mark, m.comment, m.actor) for m in view.marks] == [
        ("c1", "checked", "matches para 1", "ana")
    ]
    assert view == await service.review_marks(svc.db, run_id)
    async with svc.db.session() as s:
        record = await records.load_record(s, run_id)
    assert [(m.claim_id, m.mark, m.actor) for m in record.review_marks] == [
        ("c1", "disputed", "bob"),
        ("c1", "checked", "ana"),
    ]
    assert record.review_marks[0].at <= record.review_marks[1].at
    assert record.review_marks[1].at.tzinfo is not None


async def test_the_stored_trace_carries_the_marks_made_since(svc):
    run_id = await _delivered(svc)
    stored = dump_json({"run_id": str(run_id), "state": "completed"}).encode()
    svc.storage.put(f"runs/{run_id}/trace.json", stored)
    async with svc.db.session() as s, s.begin():
        await runs.add_export(s, run_id, "trace.json", f"runs/{run_id}/trace.json", stored)
    assert await service.stored_export(svc.db, svc.storage, run_id, "trace.json") == stored
    await service.mark_claim(svc.db, run_id, "c2", ClaimMark.CHECKED, actor="ana")
    trace = json.loads(await service.stored_export(svc.db, svc.storage, run_id, "trace.json"))
    assert trace["state"] == "completed"
    assert [(m["claim_id"], m["mark"], m["actor"]) for m in trace["review_marks"]] == [
        ("c2", "checked", "ana")
    ]


async def test_marks_are_refused_for_an_unknown_claim_a_long_comment_and_no_report(svc):
    run_id = await _delivered(svc)
    with pytest.raises(runs.NotFoundError, match="claim c9 is not in the report"):
        await service.mark_claim(svc.db, run_id, "c9", ClaimMark.CHECKED)
    with pytest.raises(service.InvalidRequestError, match="at most"):
        await service.mark_claim(
            svc.db, run_id, "c1", ClaimMark.CHECKED, comment="x" * (service.GUIDANCE_MAX_LENGTH + 1)
        )
    pid = await svc.project("other")
    running = await svc.run(pid, [await svc.source(pid)])
    with pytest.raises(service.InvalidRunStateError, match="has no report"):
        await service.mark_claim(svc.db, running, "c1", ClaimMark.CHECKED)
    with pytest.raises(service.InvalidRunStateError, match="has no report"):
        await service.review_marks(svc.db, running)


async def test_marks_are_immutable_after_accept(svc):
    """Criterion 5."""
    run_id = await _delivered(svc)
    await service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED, actor="ana")
    await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana")
    with pytest.raises(service.ConflictError, match="was accepted; its review marks can no"):
        await service.mark_claim(svc.db, run_id, "c1", ClaimMark.DISPUTED)
    view = await service.review_marks(svc.db, run_id)
    assert not view.editable and view.checked == 1


async def test_a_mark_waiting_for_an_accepts_lock_is_refused(svc, monkeypatch):
    run_id = await _delivered(svc)
    reached, release = asyncio.Event(), asyncio.Event()
    real = runs.add_review_event

    async def slow(*args):
        reached.set()
        await release.wait()  # the accept holds the run's row lock here
        return await real(*args)

    monkeypatch.setattr(runs, "add_review_event", slow)
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT))
    await reached.wait()
    mark = asyncio.create_task(service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED))
    await asyncio.sleep(0.2)
    assert not mark.done()  # it waits for the lock
    release.set()
    await accept
    with pytest.raises(service.ConflictError, match="was accepted"):
        await mark


async def test_a_return_hands_the_disputed_claims_to_the_rerun(svc):
    """Criterion 2: one finding per disputed claim, beside the note."""
    run_id = await _delivered(svc)
    await service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED, actor="ana")
    await service.mark_claim(
        svc.db, run_id, "c3", ClaimMark.DISPUTED, comment="Which shippers?", actor="ana"
    )
    child = await _review(svc, run_id, ReviewAction.RETURN, note="Tighten", actor="ana")
    async with svc.db.session() as s:
        record = await records.load_record(s, child)
        brief = await runs.get_run_brief(s, child)
    assert brief.extra_guidance == "Reviewer note: Tighten"
    assert [(f.claim_ids, f.recommendation) for f in record.reviewer_findings] == [
        (["c3"], "Which shippers?")
    ]
    assert record.review_marks == []
    with pytest.raises(
        service.ConflictError, match=f"was returned; mark the claims of its revision {child}"
    ):
        await service.mark_claim(svc.db, run_id, "c1", ClaimMark.DISPUTED)
    assert not (await service.review_marks(svc.db, run_id)).editable


async def test_a_return_needs_a_note_or_a_disputed_claim(svc):
    run_id = await _delivered(svc)
    with pytest.raises(service.InvalidRequestError, match="note for the writer, or a claim"):
        await _review(svc, run_id, ReviewAction.RETURN, note="  ")
    await service.mark_claim(svc.db, run_id, "c2", ClaimMark.DISPUTED, comment="Too sure")
    child = await _review(svc, run_id, ReviewAction.RETURN)  # the disputed claim is enough
    async with svc.db.session() as s:
        row = await runs.get_run(s, child)
    assert row.extra_guidance == ""
    assert [f["claim_ids"] for f in row.reviewer_findings] == [["c2"]]


async def test_a_note_alone_still_returns_without_findings(svc):
    run_id = await _delivered(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="More on tariffs")
    async with svc.db.session() as s:
        row = await runs.get_run(s, child)
    assert row.reviewer_findings is None and row.extra_guidance == "Reviewer note: More on tariffs"


async def test_marks_reopen_when_the_rerun_ends_without_a_report(svc):
    run_id = await _delivered(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x")
    await _set_state(svc.db, child, "failed")
    async with svc.db.session() as s, s.begin():
        await service.reruns_ended(s, [child])
    view = await service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED)
    assert view.editable and view.checked == 1


async def test_accept_is_unchanged_without_the_opt_in(svc):
    run_id = await _delivered(svc)
    await service.mark_claim(svc.db, run_id, "c1", ClaimMark.DISPUTED)
    assert await _review(svc, run_id, ReviewAction.ACCEPT) is None
    assert (await service.run_progress(svc.db, run_id)).review.decision == "accepted"


async def test_the_opt_in_refuses_accept_until_the_key_judgment_claims_are_checked(svc):
    run_id = await _delivered(svc, require=True)
    view = await service.review_marks(svc.db, run_id)
    assert view.require_key_judgments_checked and view.key_judgment_claim_ids == ["c1", "c2"]
    with pytest.raises(service.ConflictError, match="not checked: c1, c2"):
        await _review(svc, run_id, ReviewAction.ACCEPT)
    await service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED)
    await service.mark_claim(svc.db, run_id, "c2", ClaimMark.CHECKED)
    await service.mark_claim(svc.db, run_id, "c3", ClaimMark.DISPUTED)
    with pytest.raises(service.ConflictError, match=r"\(claims disputed: c3\)"):
        await _review(svc, run_id, ReviewAction.ACCEPT)
    await service.mark_claim(svc.db, run_id, "c3", ClaimMark.CHECKED)
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana") is None
    assert (await service.run_progress(svc.db, run_id)).review.decision == "accepted"


async def test_marks_on_a_check_run_are_refused(svc):
    run_id = await _delivered(svc)
    async with svc.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).kind = "check"
    with pytest.raises(service.ConflictError, match="is a check"):
        await service.mark_claim(svc.db, run_id, "c1", ClaimMark.CHECKED)
    assert not (await service.review_marks(svc.db, run_id)).editable


async def test_production_marks_counts_only_when_the_profile_asks(svc):
    off = await _delivered(svc)
    await service.mark_claim(svc.db, off, "c1", ClaimMark.CHECKED)
    assert await service.production_marks(svc.db, off) == 0
    on = await _delivered(svc, production=True)
    assert await service.production_marks(svc.db, on) == 0
    await service.mark_claim(svc.db, on, "c1", ClaimMark.CHECKED)
    await service.mark_claim(svc.db, on, "c1", ClaimMark.DISPUTED)
    assert await service.production_marks(svc.db, on) == 2


async def test_an_old_run_without_marks_or_findings_reads_as_none(svc):
    run_id = await _delivered(svc)
    async with svc.db.session() as s:
        record = await records.load_record(s, run_id)
    assert record.review_marks == [] and record.reviewer_findings == []
