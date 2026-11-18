"""CRL-97: the earlier reports' budget, and the writer's and conveyor's checks on
`changes_from_previous`."""

import json
from datetime import UTC, datetime

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import PriorJudgment, PriorReport
from corelata.stages.convey import run_conveyor
from corelata.stages.prior import prior_report_entry, select_prior_reports
from corelata.stages.write import run_writer, without_unasked


def _report(run_id: str, text: str = "Grows.") -> PriorReport:
    return PriorReport(
        run_id=run_id,
        title="T",
        accepted_at=datetime(2026, 11, 2, 23, tzinfo=UTC),
        key_judgments=[PriorJudgment(text=text, confidence="high")],
    )


def test_the_entry_is_what_the_models_read():
    assert prior_report_entry(_report("r1")) == {
        "run_id": "r1",
        "title": "T",
        "date": "2026-11-02",
        "key_judgments": [{"text": "Grows.", "confidence": "high"}],
    }


def test_selection_keeps_the_newest_that_fit_and_cuts_the_rest():
    found = [_report("a"), _report("b"), _report("c", "x" * 400), _report("d")]
    picked = select_prior_reports(found, max_reports=3, budget_tokens=40, bytes_per_token=4.0)
    assert [(r.run_id, r.cut) for r in picked] == [("a", False), ("b", True), ("c", True)]
    roomy = select_prior_reports(found, max_reports=9, budget_tokens=10_000, bytes_per_token=4.0)
    assert [r.cut for r in roomy] == [False] * 4
    assert select_prior_reports([], max_reports=3, budget_tokens=100, bytes_per_token=4.0) == []
    assert found[1].cut is False  # the given reports are not changed


@pytest.fixture
def prior_ctx(make_ctx):
    ctx = make_ctx()
    ctx.prior_reports = [_report("r-earlier")]
    return ctx


async def test_the_writer_must_name_an_earlier_report_it_was_given(prior_ctx, fake_backend):
    draft = await run_writer(prior_ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    data["changes_from_previous"][0]["prior_run_id"] = "r-invented"
    bad = json.dumps(data)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError, match="'r-invented' is not the run_id"):
        await run_writer(prior_ctx, iteration=0, prior=None, findings=[])


async def test_a_stray_changes_list_is_dropped_without_earlier_reports(make_ctx, prior_ctx):
    draft = await run_writer(prior_ctx, iteration=0, prior=None, findings=[])
    assert draft.changes_from_previous
    plain = make_ctx()
    assert without_unasked(plain, draft).changes_from_previous == []
    assert without_unasked(prior_ctx, draft) is draft


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["changes_from_previous"].pop(),
        lambda d: d["changes_from_previous"][0].__setitem__("change", "changed"),
        lambda d: d["changes_from_previous"][0].__setitem__("prior_judgment", "Other."),
    ],
)
async def test_the_conveyor_may_not_change_what_an_entry_says(prior_ctx, fake_backend, mutate):
    draft = await run_writer(prior_ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    mutate(data)
    bad = json.dumps(data)
    fake_backend.script("conveyor", bad, bad)
    with pytest.raises(StructuredOutputError, match="changes_from_previous changed"):
        await run_conveyor(prior_ctx, iteration=0, draft=draft, findings=[])


async def test_the_conveyor_may_reword_an_explanation(prior_ctx, fake_backend):
    draft = await run_writer(prior_ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    data["changes_from_previous"][0]["explanation"] = "Reworded."
    fake_backend.script("conveyor", json.dumps(data))
    out = await run_conveyor(prior_ctx, iteration=0, draft=draft, findings=[])
    assert out.changes_from_previous[0].explanation == "Reworded."
