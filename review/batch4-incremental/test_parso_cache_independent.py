"""Independent public-parse checks: retention must not suppress source invalidation."""

import os
import time

import parso
import parso.cache as cache
import pytest

from lct.parso_cache_compat import ensure_parso_cache_timestamps


@pytest.mark.parametrize("disk_reload", [False, True])
def test_real_parse_retention_and_changed_source(tmp_path, monkeypatch, disk_reload):
    ensure_parso_cache_timestamps()
    # Isolate this check from the parser state used by the rest of the suite.
    monkeypatch.setattr(cache, "parser_cache", {})
    grammar = parso.load_grammar()
    source = tmp_path / "target.py"
    source.write_text("def first(): pass\n")
    old = time.time() - 86400
    os.utime(source, (old, old))
    cache_dir = tmp_path / "disk"
    tree = grammar.parse(path=source, cache=True, cache_path=cache_dir)
    assert tree.get_code() == "def first(): pass\n"
    if disk_reload:
        item = cache.parser_cache[grammar._hashed][source]
        item.last_used = old
        cache._save_to_file_system(grammar._hashed, source, item, cache_path=cache_dir)
        cache.parser_cache.clear()
        tree = grammar.parse(path=source, cache=True, cache_path=cache_dir)
    # Actually parse enough files to invoke the original >=600 cleanup path.
    for i in range(620):
        path = tmp_path / f"other_{i}.py"
        path.write_text(f"value = {i}\n")
        os.utime(path, (old, old))
        grammar.parse(path=path, cache=True, cache_path=cache_dir)
    item = cache.parser_cache[grammar._hashed][source]
    assert item.node is tree
    assert item.change_time == old
    assert item.last_used > old + 3600
    source.write_text("def second(): pass\n")
    os.utime(source, (old + 10, old + 10))
    changed = grammar.parse(path=source, cache=True, cache_path=cache_dir)
    assert changed.get_code() == "def second(): pass\n"
    assert changed is not tree
    assert cache.parser_cache[grammar._hashed][source].change_time == old + 10
