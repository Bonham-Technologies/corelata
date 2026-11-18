"""CRL-97: a queued run reads the key judgments of its project's accepted reports, and only
those; the trace stores which it was given."""

import uuid

import pytest

from corelata import service
from corelata.llm.payload import parse_input
from corelata.schema import ReviewAction, RunState, Verdict
from corelata.stages.audit import INITIAL_COVERAGE
from corelata.store import runs
from corelata.trace import run_trace
from tests.worker.conftest import drain, make_services, state, submit

TC7 = "icd203.tc.7"
# Project memory is off unless configured; these tests turn it on as the example config does.
ON = {"prior_judgments": {"max_reports": 3, "budget_tokens": 2000}}


@pytest.fixture
def services(db, fake_backend, tmp_path):
    return make_services(db, fake_backend, tmp_path, pipeline=ON)


async def _review(svc, run_id: uuid.UUID, action: ReviewAction, note: str = "") -> uuid.UUID | None:
    return await service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, action, note=note
    )


async def _completed(svc, project: str = "p", **opts) -> uuid.UUID:
    run_id = await submit(svc, project=project, **opts)
    await drain(svc)
    assert await state(svc.db, run_id) is RunState.COMPLETED
    return run_id


async def _accepted(svc, project: str = "p") -> uuid.UUID:
    run_id = await _completed(svc, project)
    await _review(svc, run_id, ReviewAction.ACCEPT)
    return run_id


def _tc7(record):
    [finding] = [f for f in record.findings if f.rule_id == TC7]
    return finding


def _writer_payloads(fake_backend) -> list[dict]:
    payloads = [parse_input([m.model_dump() for m in r.messages]) for r in fake_backend.requests]
    return [p for p in payloads if p["task"] == "writer"]


async def test_the_next_run_reads_the_accepted_report_and_its_trace_keeps_it(
    services, fake_backend
):
    """AC1 through the worker: the first run of a project is initial coverage; once it is
    accepted, the next run's writer reads its key judgments, tc.7 passes, and the stored trace
    (and so the API's) names the report read."""
    first = await _completed(services)
    record = await service.get_run_record(services.db, first)
    assert _tc7(record).verdict is Verdict.NOT_APPLICABLE
    assert _tc7(record).evidence == INITIAL_COVERAGE
    assert record.prior_reports == []
    await _review(services, first, ReviewAction.ACCEPT)
    fake_backend.requests = []
    second = await _completed(services)
    record = await service.get_run_record(services.db, second)
    [given] = record.prior_reports
    first_report = (await service.get_run_record(services.db, first)).report
    assert given.run_id == str(first) and given.title == first_report.title and not given.cut
    assert [j.text for j in given.key_judgments] == [k.text for k in first_report.key_judgments]
    [writer] = _writer_payloads(fake_backend)
    assert [p["run_id"] for p in writer["prior_reports"]] == [str(first)]
    assert _tc7(record).verdict is Verdict.PASS
    assert record.report.changes_from_previous[0].prior_run_id == str(first)
    assert [r.run_id for r in record.report.metadata.prior_reports] == [str(first)]
    assert run_trace(record).summary.prior_reports == record.prior_reports


async def test_only_accepted_reports_of_the_same_project_are_read(services, fake_backend):
    """AC2: returned, gate-rejected, unreviewed and other projects' runs are never read, and
    neither is the run itself; the newest accept comes first."""
    accepted = await _accepted(services)
    returned = await _completed(services)
    rerun = await _review(services, returned, ReviewAction.RETURN, note="Tighten the scope")
    await drain(services)  # the rerun completes, and nobody reviews it
    rejected = await submit(services, statement="Zebra migration across the Serengeti plains")
    await drain(services)
    assert await state(services.db, rejected) is RunState.GATE_REJECTED
    elsewhere = await _accepted(services, project="q")
    later = await _accepted(services)
    pid = await service.create_project(services.db, "p")
    async with services.db.session() as s:
        found = await runs.accepted_reports(s, pid, limit=10)
        assert [r.run_id for r in found] == [str(later), str(accepted)]
        assert found[0].accepted_at >= found[1].accepted_at
        limited = await runs.accepted_reports(s, pid, limit=1)
        assert [r.run_id for r in limited] == [str(later)]
        excluded = await runs.accepted_reports(s, pid, limit=10, exclude=later)
        assert [r.run_id for r in excluded] == [str(accepted)]
    never = {str(returned), str(rerun), str(rejected), str(elsewhere)}
    fake_backend.requests = []
    last = await _completed(services)
    record = await service.get_run_record(services.db, last)
    assert [p.run_id for p in record.prior_reports] == [str(later), str(accepted)]
    [writer] = _writer_payloads(fake_backend)
    read = {p["run_id"] for p in writer["prior_reports"]}
    assert read == {str(later), str(accepted)} and not read & never


@pytest.mark.parametrize("pipeline", [{"prior_judgments": {"max_reports": 0}}, {}])
async def test_max_reports_zero_reads_nothing_and_keeps_tc7_attested(
    db, fake_backend, tmp_path, pipeline
):
    """AC5 through the worker: `max_reports: 0`, or `prior_judgments` unset (an upgraded
    install), reads nothing: no `prior_reports` in any request or in the trace, and tc.7 is
    attested as before, not initial coverage, in an empty project or not."""
    svc = make_services(db, fake_backend, tmp_path, pipeline=pipeline)
    first = await _completed(svc)
    assert _tc7(await service.get_run_record(svc.db, first)).verdict is Verdict.ATTESTED
    await _review(svc, first, ReviewAction.ACCEPT)
    fake_backend.requests = []
    run_id = await _completed(svc)
    record = await service.get_run_record(svc.db, run_id)
    assert record.prior_reports == [] and _tc7(record).verdict is Verdict.ATTESTED
    assert all("prior_reports" not in p for p in _writer_payloads(fake_backend))
    assert "prior_reports" not in record.model_dump()
