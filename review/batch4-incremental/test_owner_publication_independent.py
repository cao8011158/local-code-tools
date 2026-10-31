"""Actual dense/graph publication and portable recovery after owner updates."""
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3

import pytest

from lct.common import ToolError, config, inventory
from lct.embedding import Embeddings, vector_key
from lct.extract import embedding_texts, extract
from lct.management import backup, restore
from lct.query import Query
from lct.storage import build, current, manifest, recover
from tests.synthetic_support import deterministic_vector, forbid_provider

helpers = runpy.run_path(str(Path(__file__).with_name("test_owner_update_independent.py")))


def seed_synthetic(c):
    # Fixture preparation is deliberately outside the measured production build.
    files, _, _ = inventory(c)
    nodes, _ = extract(files)
    texts = embedding_texts(nodes, files)
    target = next(t for t in texts if ":function:execute#" in t["node_id"])
    cache = Embeddings(c)
    try:
        for item in texts:
            cache.db.execute("insert or ignore into vectors values(?,?,?,?,?)", (
                vector_key(c["embedding"], item["text"], "document"), "document",
                deterministic_vector(item["text"]).tobytes(), "SYNTHETIC-TEST-ONLY", 0))
        cache.db.execute("insert or replace into vectors values(?,?,?,?,?)", (
            vector_key(c["embedding"], "execute", "query"), "query",
            deterministic_vector(target["text"]).tobytes(), "SYNTHETIC-TEST-ONLY", 0))
        cache.db.commit()
        assert cache.requests == 0
    finally:
        cache.close()


def check_channels(c, version, expected):
    q = Query(c)
    folder, meta = manifest(c, version)
    assert meta["dense_ready"] and meta["embedding_run"]["requests"] == 0
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = {ident: json.loads(raw) for ident, raw in db.execute("select node_id,data from nodes")}
        assert not db.execute(
            "select 1 from postings p left join nodes n using(node_id) where n.node_id is null").fetchone()
    worker = next(ident for ident, n in nodes.items() if n["qualname"] == "execute")
    for mode in ("bm25", "dense", "rrf"):
        result = q.search_code("execute", mode=mode, version=version)
        assert result["version"] == version and result["results"]
        assert all(n["node_id"] in nodes for n in result["results"])
    approximate = q.search_code("execute", mode="dense", limit=10, version=version)
    exact = q.search_code("execute", mode="dense", limit=10, exact=True, version=version)
    assert {n["node_id"] for n in approximate["results"]} == {
        n["node_id"] for n in exact["results"]}
    view = q.get_relations([worker], ["CALLS"], version=version)
    assert view["version"] == version and not view["truncated"]
    targets = {nodes[e["target"]]["qualname"] for e in view["edges"]
               if e["source"] == worker and e.get("target") in nodes}
    assert targets == {expected}
    source = q.get_nodes([worker], version=version)
    assert source["version"] == version and source["nodes"][0]["source_origin"] == "indexed_snapshot"
    mapped = {ident for part in meta["partitions"]
              for ident in json.loads((folder / (part["stem"] + ".json")).read_text())}
    eligible = {ident for ident, n in nodes.items() if n["kind"] in {"module", "class", "function"}}
    assert mapped == eligible


def test_owner_dense_failure_recovery_and_portable_next_update(tmp_path):
    c, repo = helpers["fixture"](tmp_path, {
        "caller.py": helpers["CALLER"], "worker.py": helpers["WORKER"]})
    c["retained_versions"] = 8
    with forbid_provider():
        seed_synthetic(c)
        first = build(c, offline=True)
        check_channels(c, first["version"], "first")
        folder, meta = manifest(c, first["version"])
        old_hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                      for name in meta["artifacts"]}
        source = repo / "src/caller.py"
        source.write_text(helpers["CALLER"].replace("execute(first)", "execute(second)"))
        seed_synthetic(c)
        with pytest.raises(ToolError, match="Injected"):
            build(c, offline=True, fail_at="before_publish")
        assert current(c) == first["version"]
        assert old_hashes == {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                              for name in meta["artifacts"]}
        check_channels(c, first["version"], "first")
        second = build(c, offline=True)
        assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        check_channels(c, second["version"], "second")
        check_channels(c, first["version"], "first")
        helpers["oracle"](c, second["version"], tmp_path)
        recover(c, first["version"])
        assert current(c) == first["version"]
        check_channels(c, current(c), "first")
        recovered = build(c, offline=True)
        assert recovered["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        check_channels(c, recovered["version"], "second")
        archive = backup(c)["archive"]
        destination = tmp_path / "portable"
        restore(c, archive, destination)
        relocated = config(destination / "config.json")
        assert current(relocated) == recovered["version"]
        check_channels(relocated, current(relocated), "second")
        source.write_text(helpers["CALLER"])
        seed_synthetic(relocated)
        final = build(relocated, offline=True)
        assert final["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        check_channels(relocated, final["version"], "first")
        check_channels(c, recovered["version"], "second")
        helpers["oracle"](relocated, final["version"], tmp_path, "fresh-restored")
