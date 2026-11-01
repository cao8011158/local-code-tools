"""Public callback/container warm lifecycle across restart and failed publish."""

import json
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest

from lct.common import ToolError
from lct.graph import Graph
from lct.query import Query
from lct.storage import build, current, manifest
from tests.semantic_comparison import assert_semantic_equal
from tests.synthetic_support import forbid_provider, initialize
from tests.test_batch3_actual_acceptance import semantic


def _targets(config, version):
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        names = {node["node_id"]: node["qualname"] for (raw,) in
                 db.execute("select data from nodes") for node in [json.loads(raw)]}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for (raw,) in db.execute("select data from sites")]
    site = next(site for site in sites if names[site["execution_owner"]] == "run"
                and site["expression"] == "fn")
    return {names.get(target, target) for target in site["targets"]}


def _writer(path, name):
    path.write_text(f"import provider\ndef configure(): provider.handlers['go']=provider.{name}\n")


def test_public_consecutive_container_callback_restart_and_failed_publish(tmp_path):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    config["retained_versions"] = 8
    config["embedding"].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    for name, content in {
        "provider.py": "def first(): pass\ndef second(): pass\nhandlers={'go':first}\n",
        "getter.py": "from provider import handlers\ndef get_callback(): return handlers['go']\n",
        "consumer.py": "from getter import get_callback\ndef run():\n    fn=get_callback()\n    fn()\n",
        "idle.py": "def unrelated(): return 1\n",
    }.items():
        (repo / "src" / name).write_text(content)
    writer = repo / "src/writer.py"
    _writer(writer, "first")
    with forbid_provider():
        cold = build(config, offline=True, lexical_only=True)
    old = cold["version"]
    old_semantic = semantic(config, old)
    query = Query(config)
    with sqlite3.connect(manifest(config, old)[0] / "catalog.sqlite") as db:
        run_id = next(json.loads(raw)["node_id"] for (raw,) in
                      db.execute("select data from nodes")
                      if json.loads(raw).get("qualname") == "run")
    assert _targets(config, old) == {"first"}
    old_nodes = query.get_nodes([run_id], version=old)
    old_relations = query.get_relations([run_id], ["CALLS"], version=old)
    _writer(writer, "second")
    original = Graph.build
    def selected_only(graph, *args, **kwargs):
        assert kwargs.get("selected_owners") is not None
        return original(graph, *args, **kwargs)
    with forbid_provider(), patch.object(Graph, "build", selected_only):
        second = build(config, offline=True, lexical_only=True)
    second_version = second["version"]
    assert "second" in _targets(config, second_version)
    assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert not any(":function:unrelated#" in owner for owner in
                   second["incremental"]["analysis_scope"]["selected_owner_ids"])
    _writer(writer, "first")
    with forbid_provider(), patch.object(Graph, "build", selected_only), pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == second_version
    assert "second" in _targets(config, second_version)
    script = ("import json,sys; from lct.graph import Graph; from lct.storage import build; "
              "original=Graph.build; "
              "def_guard=''; "
              "Graph.build=lambda self,*args,**kwargs: "
              "original(self,*args,**kwargs) if kwargs.get('selected_owners') is not None "
              "else (_ for _ in ()).throw(AssertionError('full route')); "
              "print(json.dumps(build(json.load(sys.stdin),offline=True,lexical_only=True)))")
    child = subprocess.run([sys.executable, "-c", script], input=json.dumps(config),
                           text=True, capture_output=True, check=True)
    restored = json.loads(child.stdout)
    assert restored["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert _targets(config, restored["version"]) == {"first"}
    assert current(config) == restored["version"]
    assert semantic(config, old) == old_semantic
    assert query.get_nodes([run_id], version=old)["nodes"] == old_nodes["nodes"]
    assert query.get_relations([run_id], ["CALLS"], version=old)["edges"] == old_relations["edges"]
    fresh_config = dict(config, data=str(tmp_path / "fresh"))
    with forbid_provider():
        fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, restored["version"]),
                          semantic(fresh_config, fresh["version"]))
