"""Root-owned checks of negative submodule lookup invalidation and its actual SQL."""
import json
import sqlite3

import pytest

from lct.storage import FileDependencies, GRAPH_SITES, build, manifest
from tests.synthetic_support import initialize


@pytest.mark.parametrize("noise", [0, 25])
def test_aliased_namespace_lookup_is_indexed_before_target_exists(tmp_path, noise):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/pkg").mkdir()
    (repo / "src/pkg/other.py").write_text("def other(): pass\n")
    (repo / "src/caller.py").write_text("from pkg import foo as chosen\ndef run(): return chosen()\n")
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"from different_{i} import value\n")
    result = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, result["version"])
    owner = ("synthetic-review", "src/caller.py")
    with sqlite3.connect(folder / GRAPH_SITES) as db:
        old = [json.loads(row[0]) for row in db.execute("select data from sites")]
    with FileDependencies(folder, meta) as deps:
        statements = []
        deps.db.set_trace_callback(statements.append)
        assert deps.importers("synthetic-review", "pkg.foo") == {owner}
        assert deps.requesters("synthetic-review", "pkg.foo") == {owner}
        assert deps.importers("synthetic-review", "pkg.chosen") == set()
        assert deps.importers("foreign-repository", "pkg.foo") == set()
        # The same requester has a direct pkg key, so exact lookup already covers it.
        assert deps.has_descendant_requesters("synthetic-review", "pkg") is False
        deps.db.set_trace_callback(None)
        plans = [list(deps.db.execute("explain query plan " + sql)) for sql in statements]
        for plan in plans:
            text = " ".join(str(row[3]) for row in plan)
            assert "SEARCH" in text and "SCAN" not in text, text
        print({"unrelated_imports": noise, "queries": len(statements), "plans": plans})
    (repo / "src/pkg/foo.py").write_text("def foo(): return 1\n")
    updated = build(config, offline=True, lexical_only=True)
    new_folder, _ = manifest(config, updated["version"])
    with sqlite3.connect(new_folder / GRAPH_SITES) as db:
        new = [json.loads(row[0]) for row in db.execute("select data from sites")]
    before = next(s for s in old if "caller.py" in s["execution_owner"])
    after = next(s for s in new if "caller.py" in s["execution_owner"])
    assert before["unknown_origin"] is True
    assert after["unknown_origin"] is False
    # The dependency repair does not remove the separate conservative admission gate.
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
