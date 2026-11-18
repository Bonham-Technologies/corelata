import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

from corelata_api import pack_index
from corelata_api.pack_index import PackIndex


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _team(packs, version: str) -> None:
    team = packs / "team"
    (team / "rules").mkdir(parents=True, exist_ok=True)
    meta = {"name": "team", "version": version, "extends": "icd203-base"}
    (team / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    later = time.time() + (10 if version != "1.0" else 0)
    os.utime(team / "pack.yaml", (later, later))


def _counting(monkeypatch, name: str) -> dict[str, int]:
    real = getattr(pack_index, name)
    calls = {"n": 0}

    def counting(packs_dir):
        calls["n"] += 1
        return real(packs_dir)

    monkeypatch.setattr(pack_index, name, counting)
    return calls


def test_the_listing_is_restatted_at_most_once_per_interval(tmp_path, monkeypatch):
    stats = _counting(monkeypatch, "pack_dirs_signature")
    packs = tmp_path / "packs"
    _team(packs, "1.0")
    clock = Clock()
    index = PackIndex(packs, min_interval_s=1.0, clock=clock)
    assert [p.name for p in index.listing()] == ["icd203-base", "team"]
    assert stats["n"] == 1  # the first call stats
    clock.now += 0.5
    assert index.names() == {"icd203-base", "team"}
    index.listing()
    assert stats["n"] == 1  # inside the interval: the last listing, no stat
    _team(packs, "1.1")
    assert {p.name: p.version for p in index.listing()}["team"] == "1.0"  # up to 1 s stale
    clock.now += 0.5  # exactly min_interval_s after the stat
    assert {p.name: p.version for p in index.listing()}["team"] == "1.1"
    assert stats["n"] == 2


def test_an_unchanged_signature_keeps_the_listing_without_reparsing(monkeypatch):
    parses = _counting(monkeypatch, "list_packs")
    clock = Clock()
    index = PackIndex(None, min_interval_s=1.0, clock=clock)
    first = index.listing()
    clock.now += 5
    assert index.listing() is first and parses["n"] == 1


def test_concurrent_callers_share_one_walk(monkeypatch):
    real = pack_index.pack_dirs_signature
    calls = {"n": 0}

    def slow(packs_dir):
        calls["n"] += 1
        time.sleep(0.05)
        return real(packs_dir)

    monkeypatch.setattr(pack_index, "pack_dirs_signature", slow)
    index = PackIndex(None, min_interval_s=60.0, clock=Clock())
    barrier = threading.Barrier(2)

    def call():
        barrier.wait()
        return index.listing()

    with ThreadPoolExecutor(2) as pool:
        first, second = [f.result() for f in [pool.submit(call), pool.submit(call)]]
    assert calls["n"] == 1 and first is second
