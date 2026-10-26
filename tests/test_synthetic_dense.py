"""API-free dense/HNSW/RRF integration over explicitly synthetic, deterministic data."""

from pathlib import Path

import pytest

from lct.common import ToolError
from lct.query import Query
from lct.storage import build, current, manifest
from tests.synthetic_support import QUERY, build_fixture, forbid_provider, initialize, query_fixture


def test_synthetic_three_channels_and_exact(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    m = build_fixture(c)
    found, docs = query_fixture(c)
    assert m["dense_ready"] and docs["results"]
    assert all(r["results"] for r in found.values())
    assert found["dense"]["results"][0]["qualname"] == "base_weight"
    q = Query(c)
    with forbid_provider():
        approximate = q.search_code(QUERY, mode="dense", limit=3)
        exact = q.search_code(QUERY, mode="dense", exact=True, limit=3)
        all_levels = q.search_code(QUERY, level="all", mode="dense", limit=3)
    assert {n["node_id"] for n in approximate["results"]} == {
        n["node_id"] for n in exact["results"]
    }
    assert [n["kind"] for n in all_levels["results"]] == ["module", "class", "function"]


def test_synthetic_filter_page_source_and_relations(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    build_fixture(c)
    q = Query(c)
    with forbid_provider():
        page = q.search_code(
            QUERY, mode="rrf", repositories=["synthetic-review"], candidates=10, limit=1
        )
        following = q.search_code(
            QUERY,
            mode="rrf",
            repositories=["synthetic-review"],
            candidates=10,
            limit=1,
            cursor=page["next_cursor"],
        )
    assert page["has_more"] and following["version"] == page["version"]
    assert following["results"][0]["node_id"] != page["results"][0]["node_id"]
    nid = page["results"][0]["node_id"]
    source = q.get_nodes([nid])["nodes"][0]
    assert source["live_file_matches"] and source["source_origin"] == "indexed_snapshot"
    owners = q.get_relations([nid], ["CONTAINS"], "in")
    assert owners["edges"]
    with pytest.raises(ToolError, match="Unknown repository"):
        q.search_code(QUERY, mode="bm25", repositories=["missing"])


def test_synthetic_change_delete_move_and_failure(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    first = build_fixture(c)
    q = Query(c)
    with forbid_provider():
        old_page = q.search_code(QUERY, mode="dense", candidates=10, limit=1)
    file = repo / "src/weights.py"
    file.write_text(
        file.read_text(encoding="utf-8-sig").replace("quantity * 2", "quantity * 3"),
        encoding="utf-8",
    )
    second = build_fixture(c)
    assert second["incremental"]["nodes_updated"] > 0
    with forbid_provider():
        assert (
            q.search_code(
                QUERY, mode="dense", candidates=10, limit=1, cursor=old_page["next_cursor"]
            )["version"]
            == first["version"]
        )
    (repo / "src/new.py").write_text(
        'def added():\n """Synthetic weight addition."""\n return 1\n', encoding="utf-8"
    )
    build_fixture(c)
    (repo / "src/new.py").unlink()
    file.rename(repo / "src/moved.py")
    moved = build_fixture(c)
    assert moved["incremental"]["nodes_removed"] > 0
    before = current(c)
    with pytest.raises(ToolError, match="Injected"):
        build(c, offline=True, fail_at="before_publish")
    assert current(c) == before
    with forbid_provider():
        assert q.search_code(QUERY, mode="dense")["results"]
    folder, _ = manifest(c)
    with q.db(folder) as db:
        assert not db.execute(
            "select 1 from nodes where path in ('src/weights.py','src/new.py')"
        ).fetchone()
        assert not db.execute(
            "select 1 from postings p left join nodes n using(node_id) where n.node_id is null"
        ).fetchone()


def test_readonly_acceptance_guard_never_writes_or_requests(tmp_path):
    import hashlib
    import sqlite3

    from lct.embedding import Embeddings
    from tools.readonly_cache import readonly_embeddings

    c, _ = initialize(tmp_path / "fixture")
    build_fixture(c)
    path = Path(c["data"]) / "vectors.sqlite"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with readonly_embeddings():
        cache = Embeddings(c)
        try:
            assert cache.get_many([QUERY], "query")[0].shape == (1024,)
            with pytest.raises(ToolError, match="no API"):
                cache.get_many(["missing query never requested"], "query")
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                cache.db.execute("delete from vectors")
        finally:
            cache.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
