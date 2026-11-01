"""Bounded fixed-SM source acceptance; no captured business code is executed."""

import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from lct.common import ToolError
from lct.embedding import Embeddings, vector_key
from lct.extract import embedding_texts
from lct.query import Query
from lct.storage import attach_dense, build, current, manifest, recover
from tests.synthetic_support import deterministic_vector, forbid_provider, initialize
from tests.semantic_comparison import assert_semantic_equal

FIXTURES = Path(__file__).resolve().parents[1] / "review/batch4-incremental/fixtures"
SOURCE_COMMIT = "a7b0804d5635e185a79ff3c1d1fa6241c2b858fe"
THREE = {
    "actual-related-source": ("_execution.py",),
    "actual-source-subset": ("errors.py", "item_units.py"),
}
SIX = {
    "actual-related-source": ("combat.py", "dnd_runtime.py", "item_package.py"),
    "actual-source-subset": ("availability.py", "errors.py", "item_units.py"),
}
NINE = {
    "actual-related-source": (
        "service.py", "dnd_runtime.py", "item_package.py",
        "combat.py", "world_containers.py", "_execution.py"),
    "actual-source-subset": ("availability.py", "errors.py", "item_units.py"),
}
SEMANTIC = {
    "catalog.sqlite": ("nodes", "edges"),
    "graph-sites.sqlite": (
        "sites", "query_observations", "import_dependencies", "import_requests",
        "analysis_reads", "analysis_watches", "analysis_input_scopes",
        "analysis_input_members", "analysis_input_consumers",
        "value_nodes", "value_edges", "value_reads",
        "unit_source_supports", "unit_container_subscriptions",
        "unit_container_writes", "unit_analysis_reads", "unit_analysis_watches",
        "unit_input_events"),
}


def prepare(tmp_path, groups):
    c, repo = initialize(tmp_path / "actual-fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    c["retained_versions"] = 8
    c["embedding"].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    source_files = {}
    for group, names in groups.items():
        directory = FIXTURES / group
        provenance = json.loads((directory / "provenance.json").read_text())
        assert provenance["commit"] == SOURCE_COMMIT
        for name in names:
            relative = f"src/trpg_state_machine/{name}"
            raw = (directory / relative).read_bytes()
            expected = provenance["files"][relative]
            assert len(raw) == expected["bytes"]
            assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
            blob = subprocess.run(["git", "hash-object", "--stdin"], input=raw,
                                  capture_output=True, check=True).stdout.decode().strip()
            assert blob == expected["git_blob_sha1"]
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            source_files[relative] = expected
    return c, repo, source_files


def semantic(c, version):
    folder, _ = manifest(c, version)
    results = {}
    for filename, tables in SEMANTIC.items():
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                # Include every semantic column, including import ordinal and
                # actual indexed origin rows. Ignore physical insertion order.
                results[table] = sorted(tuple(str(v) for v in row)
                                        for row in db.execute("select * from " + table))
    return results


def full_equal(tmp_path, c, result, name, *, traversal_independent=False):
    oracle_config = dict(c, data=str(tmp_path / ("fresh-" + name)))
    with forbid_provider():
        fresh = build(oracle_config, offline=True, lexical_only=True)
    actual, expected = semantic(c, result["version"]), semantic(oracle_config, fresh["version"])
    if traversal_independent:
        assert_semantic_equal(actual, expected)
    else:
        assert actual == expected
    return fresh


def seed_frozen_dense(c, version, query):
    """Cache synthetic vectors from the frozen SQLite catalog; no source reparse."""
    folder, _ = manifest(c, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = [json.loads(raw) for (raw,) in db.execute(
            "select data from nodes order by node_id")]
        files = [dict(repository=r, path=p, text=t) for r, p, t in
                 db.execute("select repository,path,text from files")]
    texts = embedding_texts(nodes, files)
    target = next(t for t in texts if t["node_id"].endswith(":function:valid_item_unit#1.1"))
    cache = Embeddings(c)
    started = time.monotonic()
    try:
        for item in texts:
            cache.db.execute("insert or ignore into vectors values(?,?,?,?,?)", (
                vector_key(c["embedding"], item["text"], "document"), "document",
                deterministic_vector(item["text"]).tobytes(), "SYNTHETIC-TEST-ONLY", 0))
        for request in (query, "valid_item_unit"):
            cache.db.execute("insert or ignore into vectors values(?,?,?,?,?)", (
                vector_key(c["embedding"], request, "query"), "query",
                deterministic_vector(target["text"]).tobytes(), "SYNTHETIC-TEST-ONLY", 0))
        cache.db.commit()
        assert cache.requests == 0
    finally:
        cache.close()
    return target["node_id"], len(texts), time.monotonic() - started


def test_nine_original_bytes_limited_graph_bm25_and_attached_real_usearch(tmp_path):
    c, repo, original = prepare(tmp_path, NINE)
    assert len(original) == 9
    with forbid_provider():
        lexical = build(c, offline=True, lexical_only=True)
    assert lexical["graph"]["analysis_limited"] is True
    assert lexical["graph"]["association_evaluations"] == 20000
    old_version = lexical["version"]
    old_semantic = semantic(c, old_version)
    q = Query(c)
    with forbid_provider():
        bm25 = q.search_code("valid_item_unit", mode="bm25", version=old_version)
    assert bm25["version"] == old_version and bm25["results"]
    query = "synthetic actual-item validation query"
    target, count, seed_seconds = seed_frozen_dense(c, old_version, query)
    with forbid_provider():
        dense = attach_dense(c, old_version, offline=True)
        nearest = q.search_code(query, mode="dense", version=dense["version"], limit=5)
        exact = q.search_code(query, mode="dense", exact=True,
                              version=dense["version"], limit=5)
        fused = q.search_code("valid_item_unit", mode="rrf",
                              version=dense["version"], limit=5)
    folder, metadata = manifest(c, dense["version"])
    assert dense["dense_ready"] and dense["embedding_run"]["requests"] == 0
    assert dense["graph"] == lexical["graph"] and metadata["version"] == current(c)
    assert metadata["artifacts"]["catalog.sqlite"] == lexical["artifacts"]["catalog.sqlite"]
    assert all((folder / (part["stem"] + ".usearch")).is_file()
               for part in metadata["partitions"])
    assert target in {r["node_id"] for r in nearest["results"]}
    assert target in {r["node_id"] for r in exact["results"]}
    assert fused["results"] and nearest["version"] == exact["version"] == dense["version"]
    assert semantic(c, dense["version"]) == old_semantic
    assert q.get_nodes([target], version=dense["version"])["version"] == dense["version"]
    assert q.get_relations([target], ["CONTAINS"], "in",
                           version=dense["version"])["version"] == dense["version"]
    print(json.dumps(dict(group="nine", files=len(original), vector_chunks=count,
                          seed_seconds=round(seed_seconds, 4),
                          association=lexical["graph"]["association_evaluations"],
                          jedi=lexical["graph"]["jedi_queries_executed"],
                          sites=lexical["graph"]["call_sites"],
                          dense_partitions=len(metadata["partitions"]))), flush=True)
    # A changed genuine file cannot admit owner reuse after the limited graph.
    source = repo / "src/trpg_state_machine/_execution.py"
    source.write_bytes(source.read_bytes().replace(b'"actor"', b'"actor_b3"', 1))
    with forbid_provider():
        updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert updated["incremental"]["analysis_scope"]["reason"] == "previous-owner-evidence-unavailable"
    assert updated["graph"]["analysis_limited"]
    assert semantic(c, old_version) == old_semantic
    full_equal(tmp_path, c, updated, "nine-edited")


def test_three_actual_sources_owner_lifecycle_and_membership(tmp_path):
    c, repo, original = prepare(tmp_path, THREE)
    assert len(original) == 3
    with forbid_provider():
        first = build(c, offline=True, lexical_only=True)
    assert not first["graph"]["analysis_limited"]
    before = semantic(c, first["version"])
    path = repo / "src/trpg_state_machine/_execution.py"
    path.write_bytes(path.read_bytes().replace(b'"actor"', b'"actor_b3"', 1))
    with forbid_provider():
        changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert changed["incremental"]["analysis_scope"]["python_files_parsed"] == 1
    assert current(c) == changed["version"]
    full_equal(tmp_path, c, changed, "three-changed")
    assert semantic(c, first["version"]) == before
    with forbid_provider(), pytest.raises(ToolError, match="Injected"):
        build(c, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(c) == changed["version"]
    recover(c, first["version"])
    assert current(c) == first["version"]
    with forbid_provider():
        retried = build(c, offline=True, lexical_only=True)
    assert retried["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    full_equal(tmp_path, c, retried, "three-retried")
    added_path = repo / "src/acceptance_extra.py"
    added_path.write_text("def isolated_b3():\n    return 1\n")
    with forbid_provider():
        added = build(c, offline=True, lexical_only=True)
    assert added["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert added["incremental"]["analysis_scope"]["reason"] == "python-membership-changed"
    full_equal(tmp_path, c, added, "three-added")
    added_path.unlink()
    with forbid_provider():
        deleted = build(c, offline=True, lexical_only=True)
    assert deleted["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert deleted["incremental"]["analysis_scope"]["reason"] == "python-membership-changed"
    full_equal(tmp_path, c, deleted, "three-deleted")
    q = Query(c)
    with forbid_provider():
        old = q.search_code("valid_item_unit", mode="bm25", version=first["version"])
        now = q.search_code("valid_item_unit", mode="bm25", version=deleted["version"])
    assert old["version"] == first["version"] and now["version"] == current(c)
    assert old["results"] and now["results"]
    print(json.dumps(dict(group="three", owner_mode=changed["incremental"]["analysis_scope"]["mode"],
                          parsed=changed["incremental"]["analysis_scope"]["python_files_parsed"],
                          membership_add=added["incremental"]["analysis_scope"]["reason"],
                          membership_delete=deleted["incremental"]["analysis_scope"]["reason"])),
                     flush=True)


def test_complex_seed_group_missing_external_context_and_fresh_update(tmp_path):
    c, repo, original = prepare(tmp_path, SIX)
    assert len(original) == 6
    with forbid_provider():
        first = build(c, offline=True, lexical_only=True)
    assert not first["graph"]["analysis_limited"]
    sites = semantic(c, first["version"])["sites"]
    assert sites
    source = repo / "src/trpg_state_machine/dnd_runtime.py"
    source.write_bytes(source.read_bytes() + b"\n# B3 source comment, semantics unchanged\n")
    with forbid_provider():
        updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["python_files_parsed"] >= 1
    full_equal(tmp_path, c, updated, "six-comment", traversal_independent=True)
    assert semantic(c, first["version"])["sites"] == sites
    unit = repo / "src/trpg_state_machine/item_units.py"
    original_bytes = unit.read_bytes()
    assert b"2**63 - 1" in original_bytes
    unit.write_bytes(original_bytes.replace(b"2**63 - 1", b"2**62 - 1", 1))
    with forbid_provider():
        changed_value = build(c, offline=True, lexical_only=True)
    assert changed_value["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert changed_value["incremental"]["analysis_scope"]["reason"] == (
        "open-receiver-source-coverage-unavailable")
    fresh = full_equal(tmp_path, c, changed_value, "six-value", traversal_independent=True)
    # These are actual semantic producer/consumer evidence, not rejected
    # candidate traversal. The oracle compares the rows exactly above.
    source_tables = ("unit_source_supports", "unit_container_subscriptions",
                     "unit_container_writes")
    got = semantic(c, changed_value["version"])
    oracle_config = dict(c, data=str(tmp_path / "fresh-six-value"))
    expected = semantic(oracle_config, fresh["version"])
    assert all(got[table] == expected[table] for table in source_tables)
    assert got["unit_source_supports"]
    print(json.dumps(dict(group="six", mode=updated["incremental"]["analysis_scope"]["mode"],
                          reason=updated["incremental"]["analysis_scope"]["reason"],
                          value_mode=changed_value["incremental"]["analysis_scope"]["mode"],
                          value_reason=changed_value["incremental"]["analysis_scope"]["reason"],
                          value_owner_association=changed_value["incremental"]["analysis_scope"].get(
                              "owner_association_evaluations", 0),
                          association=first["graph"]["association_evaluations"],
                          jedi=first["graph"]["jedi_queries_executed"])),
                     flush=True)
