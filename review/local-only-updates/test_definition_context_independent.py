"""Root reviewer: lexical import uses include definition-time and receiver context."""
import json
import runpy
import sqlite3
from pathlib import Path

from lct.storage import build, manifest
from tests.synthetic_support import forbid_provider

flows = runpy.run_path(str(Path(__file__).with_name("test_local_only_flow_independent.py")))


def test_import_appearing_updates_class_default_reference(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import first\nclass Runner:\n"
                       "    def run(self, cb=first): cb()\n"
                       "def unrelated(): return 1\n"})
    (repo / "src/provider.py").write_text("def first(): pass\n")
    updated = flows["local_update"](c)
    assert "first" in flows["call_targets"](c, updated, "Runner.run", "cb")
    # A class-body default reference is a separate public source relation.
    folder, _ = manifest(c, updated["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        names = {n["node_id"]: n["qualname"] for raw, in db.execute("select data from nodes")
                 for n in [json.loads(raw)]}
        edges = [json.loads(raw) for raw, in db.execute("select data from edges")]
    assert any(e["kind"] == "REFERENCES" and names.get(e["source"]) == "Runner"
               and names.get(e["target"]) == "first" for e in edges)
    flows["compare_fresh"](c, updated, tmp_path, "fresh-default")


def test_imported_base_appearing_updates_existing_method_receiver(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import Base\nclass Runner(Base):\n"
                       "    def run(self): self.handle()\n"
                       "def unrelated(): return 1\n"})
    (repo / "src/provider.py").write_text("class Base:\n    def handle(self): pass\n")
    updated = flows["local_update"](c)
    other = dict(c, data=str(tmp_path / "fresh-base"))
    with forbid_provider():
        fresh = build(other, offline=True, lexical_only=True)
    assert "Base.handle" in flows["call_targets"](other, fresh, "Runner.run", "self.handle")
    assert "Base.handle" in flows["call_targets"](c, updated, "Runner.run", "self.handle")
    assert not any(":function:unrelated#" in owner
                   for owner in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-base-equal")


def test_new_global_import_does_not_affect_a_shadowing_local_binding(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import later\nfrom other import leaf\n"
                       "def run(): later()\n"
                       "def unrelated():\n    later=leaf\n    later()\n",
        "other.py": "def leaf(): return 1\n"})
    (repo / "src/provider.py").write_text("def later(): return 2\n")
    updated = flows["local_update"](c)
    assert flows["call_targets"](c, updated, "run", "later") == {"later"}
    assert flows["call_targets"](c, updated, "unrelated", "later") == {"leaf"}
    assert not any(":function:unrelated#" in owner
                   for owner in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-shadow")
