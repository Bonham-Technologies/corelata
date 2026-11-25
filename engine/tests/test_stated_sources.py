"""CRL-138: what the analyst states about a source, set at upload or later, checked against the
pack's lexicon and snapshot by each run when it is queued."""

import asyncio
import json

import pytest

from corelata import service
from corelata.schema import RunKind, SourceStatement
from corelata.store import runs
from tests.ingest.test_coglossa import export as coglossa_export
from tests.standards.test_loader import write_pack
from tests.test_service import PORT_TEXT, Svc, _waiting_on_a_lock


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _stated(svc, source_id) -> dict | None:
    async with svc.db.session() as s:
        return (await runs.get_source(s, source_id)).stated


async def test_an_edit_sets_merges_and_clears_fields(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    assert await _stated(svc, sid) is None
    row = await service.edit_source(
        svc.db, svc.cfg, pid, sid, {"origin": "  Varna Daily ", "access": "direct"}
    )
    assert row.stated == {"origin": "Varna Daily", "access": "direct"}
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"descriptor": "open-source report"})
    assert await _stated(svc, sid) == {
        "descriptor": "open-source report",
        "origin": "Varna Daily",
        "access": "direct",
    }
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"origin": "", "access": " "})
    assert await _stated(svc, sid) == {"descriptor": "open-source report"}
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"descriptor": ""})
    assert await _stated(svc, sid) is None  # nothing stated reads as before


async def test_an_edit_waits_for_another_and_keeps_its_fields(svc):
    """Two edits at once: the second waits at the source's row lock and merges into what the
    first wrote, rather than writing over it from the statement it read before."""
    pid = await svc.project()
    sid = await svc.source(pid)
    async with svc.db.session() as s, s.begin():
        await runs.get_source(s, sid, lock=True)
        second = asyncio.create_task(
            service.edit_source(svc.db, svc.cfg, pid, sid, {"access": "direct"})
        )
        for _ in range(200):
            if await _waiting_on_a_lock(svc.db):
                break
            assert not second.done(), "the second edit went past the source's lock"
            await asyncio.sleep(0.05)
        else:
            pytest.fail("the second edit never waited on the source's lock")
        await runs.set_source_statement(s, sid, SourceStatement(origin="Varna Daily"))
    row = await second
    assert row.stated == {"origin": "Varna Daily", "access": "direct"}


async def test_an_edit_is_checked_against_the_lexicon_and_its_limits(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    with pytest.raises(service.InvalidRequestError, match="descriptor 'gossip' is not in"):
        await service.edit_source(svc.db, svc.cfg, pid, sid, {"descriptor": "gossip"})
    with pytest.raises(service.InvalidRequestError, match="access 'rumour' is not in"):
        await service.edit_source(svc.db, svc.cfg, pid, sid, {"access": "rumour"})
    with pytest.raises(service.InvalidRequestError, match="date_of_information: String should"):
        await service.edit_source(svc.db, svc.cfg, pid, sid, {"date_of_information": "x" * 101})
    other = await svc.project("other")
    with pytest.raises(runs.NotFoundError, match="not in project"):
        await service.edit_source(svc.db, svc.cfg, other, sid, {"origin": "x"})
    assert await _stated(svc, sid) is None


async def test_an_upload_sets_the_statement_and_a_repeat_upload_edits_it(svc):
    pid = await svc.project()
    data = PORT_TEXT.encode()
    first = await service.store_source(
        svc.db, svc.storage, pid, "port.txt", data, statement={"origin": "Varna Daily"}
    )
    [sid] = first.ids
    assert await _stated(svc, sid) == {"origin": "Varna Daily"}
    again = await service.store_source(
        svc.db, svc.storage, pid, "port.txt", data, statement={"access": "indirect"}
    )
    assert again.existing and again.ids == [sid]
    assert await _stated(svc, sid) == {"origin": "Varna Daily", "access": "indirect"}
    plain = await service.store_source(svc.db, svc.storage, pid, "port.txt", data)
    assert plain.existing and await _stated(svc, sid) == {
        "origin": "Varna Daily",
        "access": "indirect",
    }


async def test_a_coglossa_upload_states_the_translation_not_its_guide(svc):
    pid = await svc.project()
    data = json.dumps(coglossa_export()).encode("utf-8")
    main, guide = await service.add_source(
        svc.db,
        svc.storage,
        pid,
        "letter.coglossa.json",
        data,
        coglossa_export=True,
        statement={"origin": "Ministry letter"},
    )
    assert await _stated(svc, main) == {"origin": "Ministry letter"}
    assert await _stated(svc, guide) is None


async def test_a_run_keeps_the_statement_it_was_queued_with(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    plain = await svc.source(pid, text="Shippers welcomed Varna.", name="b.md")
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"origin": "Varna Daily"})
    first = await svc.run(pid, [sid, plain])
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"origin": "Port press office"})
    second = await svc.run(pid, [sid, plain])
    old = await service.get_run_record(svc.db, first)
    new = await service.get_run_record(svc.db, second)
    assert old.sources[0].stated == SourceStatement(origin="Varna Daily")
    assert new.sources[0].stated == SourceStatement(origin="Port press office")
    assert "stated" not in old.model_dump(mode="json")["sources"][1]


async def test_a_check_run_states_nothing_over_the_report_it_checks(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    report = await svc.source(pid, text="Key judgment: Varna grew.", name="report.md")
    await service.edit_source(svc.db, svc.cfg, pid, sid, {"origin": "Varna Daily"})
    run_id = await svc.run(pid, [sid], kind=RunKind.CHECK, report_source_id=report)
    record = await service.get_run_record(svc.db, run_id)
    assert record.sources[0].stated == SourceStatement()


async def test_a_run_checks_the_statement_against_its_own_lexicon(db, tmp_path, make_config):
    """A descriptor a team profile adds may be stated, and a run with that profile takes it; a
    run without the profile is refused, naming the source."""
    write_pack(
        tmp_path / "packs",
        "house",
        rules=[],
        extends="icd203-base",
        template=None,
        lexicon=None,
        profiles={
            "liaison": {
                "name": "liaison",
                "extends": "house",
                "lexicon": {"source_descriptors": ["liaison reporting"]},
            }
        },
    )
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    house = Svc(db, tmp_path, cfg)
    pid = await house.project()
    sid = await house.source(pid)
    await service.edit_source(house.db, cfg, pid, sid, {"descriptor": "liaison reporting"})
    with pytest.raises(
        service.InvalidRequestError,
        match="source port.txt: descriptor 'liaison reporting' is not in the lexicon",
    ):
        await house.run(pid, [sid])
    assert await house.run(pid, [sid], profile="liaison")
