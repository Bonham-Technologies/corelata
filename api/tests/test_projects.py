import asyncio
import json
import uuid
from datetime import datetime

from corelata.ingest import ocr
from corelata.testing.pdf import Scan, make_pdf

from tests.conftest import STATEMENT, coglossa_export, project_with_source, set_run_state

HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)


def tsv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def _word(block, par, line, word, conf, text):
    return f"5\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t1\t1\t{conf}\t{text}"


PORT_TEXT = (
    "The port of Varna handles grain, containers and general cargo.\n\n"
    "A second grain terminal is planned for 2027.\n\n"
    "Shippers expect waiting times to fall."
)


async def _project(api, name="Black Sea") -> dict:
    response = await api.client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def _upload(api, project_id, filename, data: bytes, **form) -> object:
    return await api.client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )


async def test_create_list_and_get_projects(api):
    project = await _project(api)
    assert project["name"] == "Black Sea" and uuid.UUID(project["id"]) and project["created_at"]
    # a new project has nothing to summarise yet (M18 spec §7.1)
    assert project["last_activity_at"] == project["created_at"]
    assert (project["reports_writing"], project["reports_to_review"]) == (0, 0)
    assert project["latest_run"] is None
    assert (await api.client.get("/api/projects")).json() == [project]
    assert (await api.client.get(f"/api/projects/{project['id']}")).json() == project
    duplicate = await api.client.post("/api/projects", json={"name": "Black Sea"})
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert (await api.client.post("/api/projects", json={"name": ""})).status_code == 422
    assert (await api.client.post("/api/projects", json={"name": "x" * 201})).status_code == 422
    assert (await api.client.get(f"/api/projects/{uuid.uuid4()}")).status_code == 404
    assert (await api.client.get("/api/projects/not-a-uuid")).status_code == 422


async def test_upload_a_file_source(api):
    project = await _project(api)
    response = await _upload(api, project["id"], "Mon rapport (v2).txt", PORT_TEXT.encode())
    assert response.status_code == 201, response.text
    [source] = response.json()
    assert source["project_id"] == project["id"] and source["kind"] == "file"
    assert source["name"] == "Mon rapport (v2).txt" and source["format"] == "txt"
    assert len(source["sha256"]) == 64 and source["provenance"] == {}
    listed = await api.client.get(f"/api/projects/{project['id']}/sources")
    assert listed.status_code == 200 and listed.json() == [source]
    stored = [p for p in api.storage_root.rglob("*") if p.is_file()]
    assert [p.name for p in stored] == ["Mon_rapport__v2_.txt"]


async def test_upload_a_coglossa_export_gives_the_translation_and_its_guide(api):
    project = await _project(api)
    data = json.dumps(coglossa_export()).encode("utf-8")
    response = await _upload(
        api, project["id"], "letter.coglossa.json", data, kind="coglossa_export"
    )
    assert response.status_code == 201, response.text
    translation, guide = response.json()
    assert translation["kind"] == "coglossa_export"
    assert translation["provenance"]["coglossa_run_id"] == "run-42"
    assert guide["format"] == "coglossa-guide"
    assert len((await api.client.get(f"/api/projects/{project['id']}/sources")).json()) == 2
    bad = await _upload(api, project["id"], "letter.txt", b"hello", kind="coglossa_export")
    assert bad.status_code == 422 and "not valid JSON" in bad.json()["detail"]


async def test_upload_rejections(api):
    project = await _project(api)
    empty = await _upload(api, project["id"], "x.txt", b"")
    assert empty.status_code == 422 and empty.json()["detail"] == "x.txt is empty"
    png = await _upload(api, project["id"], "x.png", b"\x89PNG")
    assert png.status_code == 422 and "unsupported file type" in png.json()["detail"]
    blank = await _upload(api, project["id"], "blank.txt", b"\n\n  \n")
    assert blank.status_code == 422 and "no usable text" in blank.json()["detail"]
    no_file = await api.client.post(f"/api/projects/{project['id']}/sources", data={"kind": "file"})
    assert no_file.status_code == 422
    bad_kind = await _upload(api, project["id"], "x.txt", b"hello", kind="zip")
    assert bad_kind.status_code == 422
    unknown = await _upload(api, uuid.uuid4(), "x.txt", b"hello")
    assert unknown.status_code == 404
    assert (await api.client.get(f"/api/projects/{uuid.uuid4()}/sources")).status_code == 404
    assert not list(api.storage_root.rglob("*.txt"))


async def test_upload_too_large_leaves_no_file(make_api):
    async with make_api(api={"max_upload_mb": 1, "progress_poll_s": 0.02}) as api:
        project = await _project(api)
        response = await _upload(api, project["id"], "big.txt", b"x" * (1024 * 1024 + 1))
        assert response.status_code == 413
        assert response.json()["detail"] == (
            "big.txt is larger than the 1 MB upload limit (api.max_upload_mb)"
        )
        assert not list(api.storage_root.rglob("*"))
        assert (await api.client.get(f"/api/projects/{project['id']}/sources")).json() == []


async def test_a_scanned_pdf_is_read_by_ocr_off_the_event_loop(make_api, monkeypatch):
    """CRL-95 (AC1, AC2): with ingest.ocr: auto the upload reads the scanned page before it
    answers, in a worker thread, and records it; with OCR off it is refused with needs_ocr."""
    on_loop: list[bool] = []

    def read(image, languages):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            on_loop.append(False)
        else:  # pragma: no cover - the failure this test exists to catch
            on_loop.append(True)
        assert languages == ("eng", "fra")
        return tsv(_word(1, 1, 1, 1, 91, "Varna."))

    monkeypatch.setattr(ocr, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr, "DPI", 20)
    monkeypatch.setattr(ocr, "read_image", read)
    pdf = make_pdf([Scan(("Varna.",)), ["Page two."]])
    async with make_api(ingest={"ocr": "auto", "ocr_languages": ["eng", "fra"]}) as api:
        project = await _project(api)
        response = await _upload(api, project["id"], "scan.pdf", pdf)
        assert response.status_code == 201, response.text
        [source] = response.json()
        assert source["provenance"] == {"ocr_pages": [1], "ocr_languages": ["eng", "fra"]}
        assert on_loop == [False]
    async with make_api() as api:
        project = await _project(api, "No OCR")
        refused = await _upload(api, project["id"], "scan.pdf", pdf)
        assert refused.status_code == 422
        assert refused.json()["detail"].startswith("scan.pdf needs OCR (needs_ocr): page(s) 1")


async def test_projects_carry_the_sidebar_summary_and_runs_their_decision(api):
    """M18 spec §7.1 and §7.2: the list, one project and the run list agree."""
    pid, sid = await project_with_source(api, "summary")
    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
    first = (await api.client.post("/api/runs", json=body)).json()
    second = (await api.client.post("/api/runs", json=body)).json()
    await set_run_state(api.db, first["run_id"], "completed")
    to_review = (await api.client.get(f"/api/projects/{pid}")).json()
    assert (to_review["reports_writing"], to_review["reports_to_review"]) == (1, 1)
    accept = await api.client.post(f"/api/runs/{first['run_id']}/review", json={"action": "accept"})
    assert accept.status_code == 200, accept.text
    [view] = [p for p in (await api.client.get("/api/projects")).json() if p["id"] == pid]
    assert (view["reports_writing"], view["reports_to_review"]) == (1, 0)
    assert view["latest_run"] == {
        "run_id": second["run_id"],
        "state": "created",
        "status": None,
        "decision": None,
        "child_state": None,
    }
    assert datetime.fromisoformat(view["last_activity_at"]) >= datetime.fromisoformat(
        second["created_at"]
    )
    assert (await api.client.get(f"/api/projects/{pid}")).json() == view
    page = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]
    assert [(r["review_decision"], r["review_child_state"]) for r in page] == [
        (None, None),
        ("accepted", None),
    ]
