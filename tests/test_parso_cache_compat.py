"""Real Parso cache paths for the supported Jedi parser integration."""

import os

import parso
import pytest
from parso import cache

from lct.parso_cache_compat import ensure_parso_cache_timestamps


def test_unsupported_parso_version_fails_before_install(monkeypatch):
    original = cache._set_cache_item
    monkeypatch.setattr(parso, "__version__", "0.8.8")
    with pytest.raises(RuntimeError, match="parso==0.8.7"):
        ensure_parso_cache_timestamps()
    assert cache._set_cache_item is original


def test_old_source_and_disk_restore_are_recently_used(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "parser_cache", {})
    monkeypatch.setattr(cache.time, "time", lambda: 1_000_000.0)
    ensure_parso_cache_timestamps()
    original_setter = cache._set_cache_item
    ensure_parso_cache_timestamps()
    assert cache._set_cache_item is original_setter

    source = tmp_path / "old.py"
    source.write_text("answer = 1\n")
    os.utime(source, (100.0, 100.0))
    grammar = parso.load_grammar()
    disk = tmp_path / "disk"
    first = grammar.parse(path=source, cache=True, cache_path=disk)
    item = cache.parser_cache[grammar._hashed][source]
    assert item.node is first
    assert item.change_time == 100.0
    assert item.last_used == 1_000_000.0

    # A real pickle contains the original (now old) last_used value.
    cache.parser_cache.clear()
    monkeypatch.setattr(cache.time, "time", lambda: 1_001_000.0)
    restored = grammar.parse(path=source, cache=True, cache_path=disk)
    assert restored is not first
    item = cache.parser_cache[grammar._hashed][source]
    assert item.node is restored
    assert item.change_time == 100.0
    assert item.last_used == 1_001_000.0

    # Source identity still drives invalidation rather than last_used.
    source.write_text("answer = 2\n")
    os.utime(source, (101.0, 101.0))
    changed = grammar.parse(path=source, cache=True, cache_path=disk)
    assert changed is not restored
    assert "answer = 2" in changed.get_code()
    assert cache.parser_cache[grammar._hashed][source].change_time == 101.0


def test_threshold_eviction_preserves_new_insertions_and_removes_old(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "parser_cache", {})
    monkeypatch.setattr(cache.time, "time", lambda: 1_000_000.0)
    ensure_parso_cache_timestamps()
    grammar = parso.load_grammar()
    for i in range(cache._CACHED_SIZE_TRIGGER):
        item = cache._NodeCacheItem(None, (), 100.0)
        item.last_used = 100.0
        cache.parser_cache.setdefault(grammar._hashed, {})[tmp_path / str(i)] = item

    source = tmp_path / "current.py"
    source.write_text("current = 1\n")
    os.utime(source, (100.0, 100.0))
    parsed = grammar.parse(path=source, cache=True, cache_path=tmp_path / "disk")
    items = cache.parser_cache[grammar._hashed]
    assert len(items) == 1
    assert items[source].node is parsed
    assert items[source].last_used == 1_000_000.0
