import os
import threading
import time
from functools import partial

import yaml
from corelata.standards.loader import PACK_NAME_MAX_LENGTH

from corelata_api import pack_index


async def test_list_packs_shows_the_builtin_pack(api):
    response = await api.client.get("/api/packs")
    assert response.status_code == 200
    [pack] = response.json()
    assert pack["name"] == "icd203-base" and pack["builtin"] and pack["error"] is None


async def test_resolved_pack_and_validation(api):
    resolved = await api.client.get("/api/packs/icd203-base/resolved")
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["name"] == "icd203-base" and body["profile"] is None
    assert [r["id"] for r in body["rules"]] == sorted(r["id"] for r in body["rules"])
    assert "docx_reference_path" not in body
    valid = await api.client.get("/api/packs/icd203-base/validate")
    assert valid.status_code == 200 and valid.json() == {"ok": True, "issues": []}
    unknown_profile = await api.client.get(
        "/api/packs/icd203-base/resolved", params={"profile": "nope"}
    )
    assert (
        unknown_profile.status_code == 422
        and "profile 'nope' not found" in unknown_profile.json()["detail"]
    )
    for path in ("/api/packs/nope/resolved", "/api/packs/nope/validate"):
        response = await api.client.get(path)
        assert response.status_code == 404 and response.json()["detail"] == "pack 'nope' not found"
    assert (await api.client.get("/api/packs/..%2Fetc/validate")).status_code in (404, 422)
    assert (await api.client.get("/api/packs/Bad_Name/validate")).status_code == 422


async def test_customer_packs_with_draft_profiles(make_api, tmp_path):
    packs = tmp_path / "packs"
    team = packs / "team"
    (team / "rules").mkdir(parents=True)
    (team / "pack.yaml").write_text(
        yaml.safe_dump({"name": "team", "version": "1.0", "extends": "icd203-base"}),
        encoding="utf-8",
    )
    (team / "profiles").mkdir()
    (team / "profiles" / "east.yaml").write_text(
        yaml.safe_dump({"name": "east", "extends": "team", "draft": True, "tone": "brisk"}),
        encoding="utf-8",
    )
    async with make_api(standards={"packs_dir": str(packs), "default_pack": "team"}) as api:
        listed = {p["name"]: p for p in (await api.client.get("/api/packs")).json()}
        assert sorted(listed) == ["icd203-base", "team"]
        assert listed["team"]["profiles"] == [{"name": "east", "draft": True, "tone": "brisk"}]
        resolved = await api.client.get("/api/packs/team/resolved", params={"profile": "east"})
        assert resolved.status_code == 200, resolved.text  # drafts may be inspected
        assert resolved.json()["profile"] == "east" and resolved.json()["tone"] == "brisk"
        valid = await api.client.get("/api/packs/team/validate")
        assert valid.json()["ok"] is True
        assert [i["level"] for i in valid.json()["issues"]] == ["warning"]
        assert "profile 'east' is a draft" in valid.json()["issues"][0]["message"]
        run = await api.client.post(
            "/api/runs",
            json={
                "project_id": "00000000-0000-0000-0000-000000000000",
                "source_ids": ["00000000-0000-0000-0000-000000000001"],
                "value_statement": "x",
                "profile": "east",
            },
        )
        assert run.status_code == 422 and "is a draft" in run.json()["detail"]


async def test_the_listing_is_read_once_until_a_pack_file_changes(make_api, tmp_path, monkeypatch):
    packs = tmp_path / "packs"
    team = packs / "team"
    (team / "rules").mkdir(parents=True)
    meta = {"name": "team", "version": "1.0", "extends": "icd203-base"}
    (team / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    real = pack_index.list_packs
    calls = {"n": 0}

    def counting(packs_dir):
        calls["n"] += 1
        return real(packs_dir)

    now = {"t": 100.0}
    monkeypatch.setattr(pack_index, "list_packs", counting)
    monkeypatch.setattr(
        "corelata_api.app.PackIndex", partial(pack_index.PackIndex, clock=lambda: now["t"])
    )
    async with make_api(standards={"packs_dir": str(packs), "default_pack": "team"}) as api:
        for _ in range(3):
            listed = (await api.client.get("/api/packs")).json()
            assert [p["name"] for p in listed] == ["icd203-base", "team"]
        assert (await api.client.get("/api/packs/team/validate")).status_code == 200
        assert (await api.client.get("/api/packs/nope/validate")).status_code == 404
        assert calls["n"] == 1  # three listings and two name checks: one read
        edited = yaml.safe_dump({**meta, "version": "1.1"})
        (team / "pack.yaml").write_text(edited, encoding="utf-8")
        later = time.time() + 10
        os.utime(team / "pack.yaml", (later, later))
        now["t"] += 1.0  # the next request may re-stat (R-M10-2)
        listed = {p["name"]: p for p in (await api.client.get("/api/packs")).json()}
        assert listed["team"]["version"] == "1.1" and calls["n"] == 2


async def test_pack_names_follow_the_shared_length_limit(api):
    longest = "a" * PACK_NAME_MAX_LENGTH
    assert (await api.client.get(f"/api/packs/{longest}/validate")).status_code == 404
    assert (await api.client.get(f"/api/packs/{longest}a/validate")).status_code == 422


async def test_the_pack_walk_runs_off_the_event_loop(make_api, monkeypatch):
    real = pack_index.pack_dirs_signature
    threads: list[bool] = []

    def recording(packs_dir):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(packs_dir)

    now = {"t": 100.0}
    monkeypatch.setattr(pack_index, "pack_dirs_signature", recording)
    monkeypatch.setattr(
        "corelata_api.app.PackIndex", partial(pack_index.PackIndex, clock=lambda: now["t"])
    )
    async with make_api() as api:
        assert (await api.client.get("/api/packs")).status_code == 200
        assert threads == [False]
        now["t"] += 2.0  # past the interval: the _known path walks again
        assert (await api.client.get("/api/packs/icd203-base/validate")).status_code == 200
        assert threads == [False, False]
