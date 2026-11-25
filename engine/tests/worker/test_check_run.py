"""CRL-94: a queued check run executes in the worker and its exports reproduce from the rows."""

import pytest

from corelata import service
from corelata.exports import render_outputs
from corelata.prompts.check import check_prompt_ids
from corelata.schema import ReportStatus, RunKind, RunState
from corelata.service import InvalidRequestError, InvalidRunStateError
from corelata.standards.schema import ResolvedPack
from corelata.store import runs
from tests.stages.conftest import PORT
from tests.worker.conftest import drain

REPORT = (
    "# Varna port outlook\n\nUNCLASSIFIED\n\n## Key judgments\n\n"
    "It is likely that the Varna port capacity expansion matters to shippers.\n\n"
    "Shipping lines will very likely move their Black Sea hubs to Varna by 2027.\n"
)


async def _project(svc):
    pid = await service.create_project(svc.db, "p")
    [sid] = await service.add_source(
        svc.db, svc.storage, pid, "port.txt", "\n\n".join(PORT).encode()
    )
    [rid] = await service.add_source(svc.db, svc.storage, pid, "outlook.md", REPORT.encode())
    return pid, sid, rid


async def test_a_queued_check_completes_and_its_exports_reproduce(services):
    pid, sid, rid = await _project(services)
    req = service.RunRequest(
        project_id=pid,
        source_ids=[sid],
        value_statement="",
        kind=RunKind.CHECK,
        report_source_id=rid,
    )
    run_id = await service.start_run(
        services.db, services.storage, services.queue, services.cfg, services.prompts, req
    )
    assert await drain(services) == 1
    progress = await service.run_progress(services.db, run_id)
    assert progress.kind is RunKind.CHECK and progress.report_source_id == str(rid)
    assert progress.state is RunState.COMPLETED and progress.status is ReportStatus.FINDINGS_OPEN
    record = await service.get_run_record(services.db, run_id)
    assert record.kind is RunKind.CHECK and record.checked_report is not None
    assert record.checked_report.name == "outlook.md" and record.prior_reports == []
    assert set(record.prompt_versions) == set(check_prompt_ids())
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    again = render_outputs(record, pack, with_claim_ids=False, formats=("json", "md", "html"))
    stored = {
        name: await service.stored_export(services.db, services.storage, run_id, name)
        for name in again
    }
    assert {k: v if isinstance(v, bytes) else v.encode() for k, v in again.items()} == stored
    assert "findings.csv" in stored
    [summary] = await service.list_runs(services.db, pid)
    assert summary.kind is RunKind.CHECK
    async with services.db.session() as s:
        [(_, found)] = await runs.project_summaries(s, pid)
    assert found.reports_to_review == 0
    with pytest.raises(InvalidRunStateError, match="is a check"):
        await service.review_run(
            services.db,
            services.storage,
            services.queue,
            services.cfg,
            services.prompts,
            run_id,
            service.ReviewAction.ACCEPT,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"report_source_id": None}, "needs report_source_id"),
        ({"source_ids": "both"}, "cannot also be one of its sources"),
        ({"parent_run_id": "x"}, "no parent run"),
        ({"kind": RunKind.REPORT, "value_statement": "Varna"}, "is for a check"),
    ],
)
async def test_a_check_request_is_validated(services, changes, message):
    import uuid

    pid, sid, rid = await _project(services)
    fields = {
        "project_id": pid,
        "source_ids": [sid],
        "value_statement": "",
        "kind": RunKind.CHECK,
        "report_source_id": rid,
        **changes,
    }
    if fields["source_ids"] == "both":
        fields["source_ids"] = [sid, rid]
    if fields.get("parent_run_id") == "x":
        fields["parent_run_id"] = uuid.uuid4()
    with pytest.raises(InvalidRequestError, match=message):
        await service.start_run(
            services.db,
            services.storage,
            services.queue,
            services.cfg,
            services.prompts,
            service.RunRequest(**fields),
        )
