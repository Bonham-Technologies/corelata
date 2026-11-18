import pytest

from corelata_api.render_cache import RenderCache


def test_returns_what_was_put_and_none_otherwise():
    cache = RenderCache(capacity=2)
    assert cache.get("r1", "html") is None
    cache.put("r1", "html", b"<p>1</p>")
    assert cache.get("r1", "html") == b"<p>1</p>"
    assert cache.get("r1", "md") is None  # the format is part of the key


def test_evicts_the_least_recently_used_entry():
    cache = RenderCache(capacity=2)
    cache.put("r1", "html", b"1")
    cache.put("r2", "html", b"2")
    assert cache.get("r1", "html") == b"1"  # r1 is now the most recent
    cache.put("r3", "html", b"3")
    assert len(cache) == 2
    assert cache.get("r2", "html") is None
    assert cache.get("r1", "html") == b"1" and cache.get("r3", "html") == b"3"


def test_putting_the_same_key_replaces_without_growing():
    cache = RenderCache(capacity=1)
    cache.put("r1", "html", b"a")
    cache.put("r1", "html", b"b")
    assert len(cache) == 1 and cache.get("r1", "html") == b"b"


def test_capacity_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        RenderCache(capacity=0)


def test_a_byte_budget_evicts_the_least_recently_used_until_the_new_entry_fits():
    cache = RenderCache(capacity=10, max_bytes=10)
    cache.put("r1", "html", b"1111")
    cache.put("r2", "html", b"2222")
    assert cache.get("r1", "html") == b"1111"  # r2 is now the oldest
    cache.put("r3", "html", b"333333")  # 8 + 6 > 10: r2 goes, then 4 + 6 fits
    assert cache.get("r2", "html") is None
    assert len(cache) == 2 and cache.total_bytes == 10
    cache.put("r4", "html", b"4")  # 10 + 1 > 10: r1, the oldest now, goes
    assert cache.get("r1", "html") is None and cache.total_bytes == 7


def test_an_entry_larger_than_the_budget_is_not_stored_and_evicts_nothing():
    cache = RenderCache(capacity=10, max_bytes=4)
    cache.put("r1", "html", b"1111")
    cache.put("r2", "html", b"22222")
    assert cache.get("r2", "html") is None
    assert cache.get("r1", "html") == b"1111" and cache.total_bytes == 4


def test_replacing_an_entry_frees_its_old_bytes():
    cache = RenderCache(capacity=10, max_bytes=8)
    cache.put("r1", "html", b"11111111")
    cache.put("r1", "html", b"11")
    assert len(cache) == 1 and cache.total_bytes == 2
    cache.put("r1", "html", b"x" * 9)  # too large now: the old value is dropped, not kept
    assert len(cache) == 0 and cache.total_bytes == 0


def test_a_zero_budget_stores_nothing():
    cache = RenderCache(max_bytes=0)
    cache.put("r1", "html", b"")
    cache.put("r2", "html", b"x")
    assert len(cache) == 0 and cache.max_bytes == 0


def test_the_budget_defaults_to_64_mib_and_must_not_be_negative():
    assert RenderCache().max_bytes == 64 * 1024 * 1024
    with pytest.raises(ValueError, match="must not be negative"):
        RenderCache(max_bytes=-1)
