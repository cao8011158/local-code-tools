"""Actual public builds: immutable Python inputs reuse only exact Jedi observations."""

import json
import sqlite3
import subprocess

import jedi
import pytest

import lct.storage as storage
from lct.incremental import module_import_dependents
from tests.synthetic_support import initialize, seed_cache


def commit(repo, message):
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-m", message],
                   check=True, capture_output=True)


def records(c, version):
    folder, m = storage.manifest(c, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = db.execute("select node_id,data from nodes order by node_id").fetchall()
        edges = db.execute("select edge_id,data from edges order by edge_id").fetchall()
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = db.execute("select data from sites order by ordinal").fetchall()
    return nodes, edges, sites, m


def full_again(c, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_same_python_inputs", lambda *_: (False, "forced-full-control", set(), False))
        return storage.build(c, lexical_only=True)


def test_committed_docs_edit_reuses_jedi_with_identical_public_evidence(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)
    (repo / "docs" / "guide.md").write_text("A changed guide.\n")
    commit(repo, "documentation only")
    reused = storage.build(c, lexical_only=True)
    assert reused["repositories"][0]["head"] != first["repositories"][0]["head"]
    assert reused["graph"]["jedi_queries_reused"] > 0
    assert reused["graph"]["jedi_queries_executed"] + reused["graph"]["jedi_queries_reused"] == reused["graph"]["jedi_queries"]
    assert reused["graph"]["query_reuse_reason"] == "python-inputs-identical"
    control = full_again(c, monkeypatch)
    assert control["graph"]["jedi_queries_reused"] == 0
    assert records(c, reused["version"])[:3] == records(c, control["version"])[:3]


@pytest.mark.parametrize("old,new", [
    ("from helper import fresh as alias\nalias()\n", "from helper import fresh as alias\nalias()\n"),
    ("from reexport import handler as alias\nalias()\n", "from reexport import handler as alias\nalias()\n"),
])
def test_python_definition_change_full_fallback_and_import_inventory(tmp_path, monkeypatch, old, new):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "caller.py").write_text(old)
    (repo / "src" / "helper.py").write_text("def previous(): pass\n")
    if "reexport" in old:
        (repo / "src" / "reexport.py").write_text("from helper import handler\n")
    commit(repo, "caller")
    first = storage.build(c, lexical_only=True)
    (repo / "src" / "helper.py").write_text("def handler(): pass\ndef fresh(): pass\n")
    (repo / "src" / "caller.py").write_text(new)
    commit(repo, "add missing exported name")
    updated = storage.build(c, lexical_only=True)
    assert updated["graph"]["query_reuse_reason"] == "python-source-or-membership-changed;local-query-only"
    assert updated["graph"]["jedi_queries_reused"] == 0
    assert updated["graph"]["import_dependency_count"] >= 1
    folder, _ = storage.manifest(c, updated["version"])
    changed = next(n for n, data in records(c, updated["version"])[0]
                   if json.loads(data).get("kind") == "module" and json.loads(data).get("qualname") == "helper")
    closure = module_import_dependents(folder / "graph-sites.sqlite", {changed})
    assert any("caller" in node for node in closure)
    assert first["version"] != updated["version"]
    control = full_again(c, monkeypatch)
    assert records(c, updated["version"])[:3] == records(c, control["version"])[:3]


def test_callback_alias_edit_keeps_full_fallback(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "handler.py").write_text("def target(): pass\ndef use(callback):\n callback()\n")
    commit(repo, "callback baseline")
    storage.build(c, lexical_only=True)
    (repo / "src" / "handler.py").write_text("def target(): pass\ndef use(callback):\n callback()\nalias = target\nuse(alias)\n")
    commit(repo, "alias call")
    updated = storage.build(c, lexical_only=True)
    assert updated["graph"]["jedi_queries_reused"] == 0
    assert updated["graph"]["query_reuse_reason"] == "python-source-or-membership-changed;local-query-only"
    control = full_again(c, monkeypatch)
    assert records(c, updated["version"])[:3] == records(c, control["version"])[:3]


def test_deleted_export_returns_to_named_unresolved_lookup(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "helper.py").write_text("def exported(): pass\n")
    (repo / "src" / "caller.py").write_text("from helper import exported as alias\nalias()\n")
    commit(repo, "export present")
    storage.build(c, lexical_only=True)
    (repo / "src" / "helper.py").write_text("def other(): pass\n")
    commit(repo, "remove export")
    updated = storage.build(c, lexical_only=True)
    assert updated["graph"]["jedi_queries_reused"] == 0
    rows = [json.loads(data) for _, data in records(c, updated["version"])[1]]
    assert any(row["kind"] == "IMPORTS" and row.get("lookup", {}).get("name") == "exported"
               and row["status"] == "unresolved" for row in rows)
    control = full_again(c, monkeypatch)
    assert records(c, updated["version"])[:3] == records(c, control["version"])[:3]


def test_changed_other_python_module_reuses_unchanged_function_local_query(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "local.py").write_text(
        "def outer():\n    def nested(): pass\n    nested()\n")
    (repo / "src" / "other.py").write_text("def unrelated(): pass\n")
    commit(repo, "local call baseline")
    storage.build(c, lexical_only=True)
    (repo / "src" / "other.py").write_text("def different(): pass\ndifferent()\n")
    commit(repo, "other module changed")
    invoked = []
    original_infer = jedi.Script.infer

    def traced_infer(script, *args, **kwargs):
        invoked.append(script.path.name)
        return original_infer(script, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(jedi.Script, "infer", traced_infer)
        updated = storage.build(c, lexical_only=True)
    assert updated["graph"]["query_reuse_reason"] == "python-source-or-membership-changed;local-query-only"
    assert updated["graph"]["jedi_queries_reused"] > 0
    assert updated["graph"]["jedi_queries_executed"] + updated["graph"]["jedi_queries_reused"] == updated["graph"]["jedi_queries"]
    assert "local.py" not in invoked and "other.py" in invoked
    control = full_again(c, monkeypatch)
    assert records(c, updated["version"])[:3] == records(c, control["version"])[:3]


def test_import_reverse_index_accepts_fragment_in_workspace_path(tmp_path):
    c, repo = initialize(tmp_path / "has#fragment" / "fixture")
    (repo / "src" / "caller.py").write_text("from weights import base_weight\n")
    result = storage.build(c, lexical_only=True)
    folder, _ = storage.manifest(c, result["version"])
    nodes = [json.loads(data) for _, data in records(c, result["version"])[0]]
    module = next(node["node_id"] for node in nodes if node["kind"] == "module"
                  and node["qualname"] == "weights")
    assert any("caller" in ident for ident in module_import_dependents(
        folder / "graph-sites.sqlite", {module}))


@pytest.mark.parametrize("mode", ["prepare_only", "on_candidate"])
def test_second_dense_build_has_prior_manifest_in_all_candidate_modes(tmp_path, mode):
    c, _ = initialize(tmp_path / "fixture")
    seed_cache(c)
    original = storage.build(c, offline=True)
    visited = []
    options = ({"prepare_only": True} if mode == "prepare_only" else
               {"on_candidate": lambda ident, folder, m, previous: visited.append((ident, previous))})
    candidate = storage.build(c, offline=True, **options)
    assert candidate["incremental"]["dense_partitions_reused"] == len(original["partitions"])
    assert candidate["incremental"]["dense_partitions_rebuilt"] == 0
    assert candidate["embedding_run"]["requests"] == 0
    assert storage.current(c) == (original["version"] if mode == "prepare_only" else candidate["version"])
    if mode == "on_candidate":
        assert visited == [(candidate["version"], original["version"])]
