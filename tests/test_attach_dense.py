"""Frozen-catalog attachment tests use only a private synthetic fixture/cache."""

import json
import sqlite3

import pytest

from lct.common import ToolError
from lct.embedding import Embeddings, vector_key
from lct.extract import embedding_texts
from lct.management import backup, restore
from lct.query import Query
from lct.storage import attach_dense, build, current, manifest
from tests.synthetic_support import (
    QUERY,
    deterministic_vector,
    forbid_provider,
    initialize,
    seed_cache,
)


def lexical_fixture(tmp_path, bom=False):
    c, repo = initialize(tmp_path / "fixture")
    if bom:
        p = repo / "src/weights.py"
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    seed_cache(c)
    old = build(c, offline=True, lexical_only=True)
    folder, _ = manifest(c)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = [json.loads(r[0]) for r in db.execute("select data from nodes order by node_id")]
        files = [dict(repository=r[0], path=r[1], text=r[2]) for r in db.execute("select repository,path,text from files")]
    cache = Embeddings(c)
    try:
        for t in embedding_texts(nodes, files):
            cache.db.execute("insert or ignore into vectors values(?,?,?,?,?)",
                             (vector_key(c["embedding"], t["text"], "document"), "document",
                              deterministic_vector(t["text"]).tobytes(), "SYNTHETIC-TEST-ONLY", 0))
        cache.db.commit()
    finally:
        cache.close()
    return c, repo, old


def test_attach_uses_frozen_catalog_and_preserves_graph(tmp_path, monkeypatch):
    c, repo, old = lexical_fixture(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Attachment must not reparse or inventory live sources")

    monkeypatch.setattr("lct.storage.inventory", forbidden)
    monkeypatch.setattr("lct.storage.extract", forbidden)
    monkeypatch.setattr("lct.storage.Graph", forbidden)
    # Even a missing source tree must not affect the captured index.
    repo.rename(repo.with_name("source-held"))
    with forbid_provider():
        dense = attach_dense(c, old["version"], offline=True)
        results = Query(c).search_code(QUERY, mode="rrf", repositories=["synthetic-review"])
        exact = Query(c).search_code(QUERY, mode="dense", exact=True)
    assert dense["version"] != old["version"] and current(c) == dense["version"]
    assert dense["dense_ready"] and results["results"] and exact["results"]
    assert dense["node_count"] == old["node_count"]
    assert dense["graph"] == old["graph"] and dense["edges"] == old["edges"]
    assert dense["source_fingerprint"] == old["source_fingerprint"]
    assert dense["artifacts"]["catalog.sqlite"] == old["artifacts"]["catalog.sqlite"]
    assert manifest(c, old["version"])[1]["artifacts"] == old["artifacts"]
    with pytest.raises(ToolError, match="already has a dense"):
        attach_dense(c, dense["version"], offline=True)


def test_fence_interruption_and_missing_cache_leave_lexical_current(tmp_path):
    c, _, old = lexical_fixture(tmp_path)
    with pytest.raises(ToolError, match="version mismatch"):
        attach_dense(c, "wrong-version", offline=True)
    with pytest.raises(ToolError, match="program hash"):
        # A changed executable must name the captured predecessor hash.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("lct.storage.program_hash", lambda: "1" * 64)
            attach_dense(c, old["version"], offline=True)
    with forbid_provider(), pytest.raises(ToolError, match="Injected interruption"):
        attach_dense(c, old["version"], offline=True, fail_at="before_publish")
    assert current(c) == old["version"]
    assert not manifest(c)[1]["dense_ready"]

    from lct.embedding import Embeddings
    cache = Embeddings(c)
    try:
        cache.db.execute("delete from vectors where kind='document'")
        cache.db.commit()
    finally:
        cache.close()
    with forbid_provider(), pytest.raises(ToolError, match="Dense cache missing"):
        attach_dense(c, old["version"], offline=True)
    assert current(c) == old["version"]


def test_frozen_utf8_bom_source_checksum(tmp_path):
    c, _, old = lexical_fixture(tmp_path, bom=True)
    with forbid_provider():
        dense = attach_dense(c, old["version"], offline=True)
    assert dense["dense_ready"] and dense["source_fingerprint"] == old["source_fingerprint"]


def test_attached_version_portable_restore(tmp_path):
    c, _, old = lexical_fixture(tmp_path)
    with forbid_provider():
        dense = attach_dense(c, old["version"], offline=True)
    archive = backup(c)["archive"]
    target = tmp_path / "downloaded-location"
    restore(c, archive, target)
    from lct.common import config
    restored = config(target / "config.json")
    with forbid_provider():
        original = Query(c).search_code(QUERY, mode="rrf")
        relocated = Query(restored).search_code(QUERY, mode="rrf")
    assert [x["node_id"] for x in original["results"]] == [x["node_id"] for x in relocated["results"]]
    assert manifest(restored)[1]["artifacts"] == dense["artifacts"]
