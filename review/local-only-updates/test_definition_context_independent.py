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
    # Fresh also keeps cb() UNKNOWN without an observed method invocation.
    # Test the actual definition-time reference, not unsupported call precision.
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


def test_new_import_flows_through_function_container_without_other_default_consumer(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import later\nfrom other import leaf\n"
                       "registry={'go':later}\n"
                       "def run(): registry['go']()\n"
                       "def unrelated(fn=leaf): fn()\n",
        "other.py": "def leaf(): return 1\n"})
    (repo / "src/provider.py").write_text("def later(): return 2\n")
    updated = flows["local_update"](c)
    assert flows["call_targets"](c, updated, "run", "registry['go']") == {"later"}
    assert not any(":function:unrelated#" in owner
                   for owner in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-container-import")


def test_new_global_import_does_not_invalidate_shadowing_nonlocal_cell(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import later\nfrom other import leaf\n"
                       "def run(): later()\n"
                       "def make():\n    later=leaf\n"
                       "    def unrelated():\n        nonlocal later\n        later()\n"
                       "    return unrelated\n",
        "other.py": "def leaf(): return 1\n"})
    (repo / "src/provider.py").write_text("def later(): return 2\n")
    updated = flows["local_update"](c)
    assert flows["call_targets"](c, updated, "run", "later") == {"later"}
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert not any(":function:make#" in owner or "make.unrelated#" in owner for owner in selected)
    flows["compare_fresh"](c, updated, tmp_path, "fresh-nonlocal")


def test_class_receiver_captured_by_returned_lambda_updates_with_new_base(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import Base\nclass Runner(Base):\n"
                       "    def make(self):\n        return lambda: self.handle()\n"
                       "def unrelated(): return 1\n"})
    (repo / "src/provider.py").write_text("class Base:\n    def handle(self): pass\n")
    updated = flows["local_update"](c)
    other = dict(c, data=str(tmp_path / "fresh-closure"))
    with forbid_provider():
        fresh = build(other, offline=True, lexical_only=True)
    owner = "Runner.make.<lambda>"
    assert flows["call_targets"](other, fresh, owner, "self.handle") == {"Base.handle"}
    assert flows["call_targets"](c, updated, owner, "self.handle") == {"Base.handle"}
    assert not any(":function:unrelated#" in name
                   for name in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-closure-equal")
