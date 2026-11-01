"""Definition-time and receiver dependencies used for owner selection."""

import ast
import json
import sqlite3

from lct.extract import python_nodes
from lct.graph import Graph
from lct.storage import build, manifest
from lct.unit_incremental import _loaded_names, _module_aliases
from tests.semantic_comparison import assert_semantic_equal
from tests.synthetic_support import forbid_provider, initialize
from tests.test_batch3_actual_acceptance import semantic
from tests.test_core import file


def test_import_use_ownership_includes_headers_and_composites_but_not_locals():
    tree = ast.parse(
        "from provider import later, Base\n"
        "registry={'go':later}\n"
        "class Runner(Base):\n"
        "    def run(self, cb=later): cb()\n"
        "def consume(): registry['go']()\n"
        "def unrelated():\n    later=other.leaf\n    later()\n"
        "def make():\n    later=other.leaf\n"
        "    def nested():\n        nonlocal later\n        later()\n"
        "    return nested\n")
    runner, consume, unrelated, make = tree.body[2:]
    assert {"Base", "later"} <= _loaded_names(runner)
    assert "registry" in _module_aliases(tree, "later")
    assert "registry" in _loaded_names(consume)
    assert "later" not in _loaded_names(unrelated)
    assert "later" not in _loaded_names(make.body[1])


def test_unknown_class_base_still_records_receiver_context_source():
    source = file("from absent import Base\nclass Runner(Base):\n"
                  "    def run(self): self.handle()\n"
                  "def unrelated(): return 1\n", "src/consumer.py")
    nodes, trees = python_nodes(source)
    edges, info = Graph(nodes, trees, [dict(name="demo", path=".", head="x",
                                            status="", closed_world=True)]).build(
                                                selected_owners=set(trees))
    byid = {n["node_id"]: n for n in nodes}
    supports = [s for s in info["_unit_supports"] if s["kind"] == "class-receiver-context"]
    assert len(supports) == 1
    assert byid[supports[0]["producer_owner"]]["qualname"] == "Runner"
    assert byid[supports[0]["consumer_owner"]]["qualname"] == "Runner.run"
    assert supports[0]["producer_location"]["expression"] == "Runner"
    assert all(e["kind"] != "CALLS" for e in edges if e["source"] == supports[0]["producer_owner"])


def test_deferred_annotations_are_not_runtime_import_consumers():
    tree = ast.parse("from __future__ import annotations\n"
                     "def idle(value: later) -> later: return 1\n"
                     "def active(value=later): return value\n")
    assert "later" not in _loaded_names(tree.body[1], deferred=True)
    assert "later" in _loaded_names(tree.body[2], deferred=True)


def test_returned_closure_has_own_class_receiver_source_without_shadowed_receiver():
    source = file("from absent import Base\nclass Runner(Base):\n"
                  "    def make(self): return lambda: self.handle()\n"
                  "    def nested(self):\n"
                  "        def callback(): return self.handle()\n"
                  "        return callback\n"
                  "    def shadow(self): return lambda self: self.handle()\n"
                  "    def make_alias(self):\n"
                  "        receiver=self\n"
                  "        return lambda: receiver.handle()\n"
                  "    def shadow_alias(self):\n"
                  "        receiver=self\n"
                  "        return lambda receiver: receiver.handle()\n"
                  "    def default_receiver(self):\n"
                  "        return lambda receiver=self: receiver.handle()\n"
                  "    @staticmethod\n"
                  "    def static(self): return lambda: self.handle()\n",
                  "src/consumer.py")
    nodes, trees = python_nodes(source)
    _, info = Graph(nodes, trees, [dict(name="demo", path=".", head="x",
                                     status="", closed_world=True)]).build(
                                         selected_owners=set(trees))
    byid = {n["node_id"]: n for n in nodes}
    supports = [s for s in info["_unit_supports"] if s["kind"] == "class-receiver-context"]
    names = {byid[s["consumer_owner"]]["qualname"] for s in supports}
    assert "Runner.make.<lambda>" in names
    assert "Runner.nested.callback" in names
    assert "Runner.make_alias.<lambda>" in names
    assert "Runner.default_receiver.<lambda>" in names
    assert "Runner.shadow.<lambda>" not in names
    assert "Runner.shadow_alias.<lambda>" not in names
    assert "Runner.static.<lambda>" not in names
    assert all(byid[s["producer_owner"]]["qualname"] == "Runner" for s in supports)
    assert any(byid[s["consumer_owner"]]["qualname"] == "Runner.make.<lambda>"
               and byid[s["detail"]["via_method"]]["qualname"] == "Runner.make"
               for s in supports)


def test_new_base_updates_returned_receiver_alias_owner(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "src/consumer.py").write_text(
        "from provider import Base\nclass Runner(Base):\n"
        "    def make(self):\n        receiver=self\n"
        "        return lambda: receiver.handle()\n"
        "def unrelated(): return 1\n")
    with forbid_provider():
        build(c, offline=True, lexical_only=True)
    (repo / "src/provider.py").write_text(
        "class Base:\n    def handle(self): pass\n")
    with forbid_provider():
        updated = build(c, offline=True, lexical_only=True)
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert any(":function:Runner.make.<lambda>#" in owner for owner in selected)
    assert not any(":function:unrelated#" in owner for owner in selected)
    folder, _ = manifest(c, updated["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        names = {n["node_id"]: n["qualname"] for raw, in db.execute("select data from nodes")
                 for n in [json.loads(raw)]}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for raw, in db.execute("select data from sites")]
    call = next(s for s in sites if names[s["execution_owner"]] == "Runner.make.<lambda>"
                and s["expression"] == "receiver.handle")
    assert {names[target] for target in call["targets"]} == {"Base.handle"}
    fresh_c = dict(c, data=str(tmp_path / "fresh"))
    with forbid_provider():
        fresh = build(fresh_c, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(c, updated["version"]),
                          semantic(fresh_c, fresh["version"]))
