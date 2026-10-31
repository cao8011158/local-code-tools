"""Opaque receiver evidence is a selected-consumer guard, not a grammar gate."""
from pathlib import Path
import runpy
import sqlite3
import json

from lct.python_analysis import Analyzer

helpers = runpy.run_path(str(Path(__file__).with_name("test_owner_update_independent.py")))


def test_real_value_edit_with_opaque_selected_receiver_matches_full(tmp_path):
    root = Path(__file__).parent / "fixtures"
    sources = {}
    for name in ("combat", "dnd_runtime", "item_package", "availability", "errors", "item_units"):
        family = "actual-source-subset" if name in {"availability", "errors", "item_units"} else "actual-related-source"
        relative = "trpg_state_machine/" + name + ".py"
        sources[relative] = (root / family / "src" / relative).read_text()
    c, repo = helpers["fixture"](tmp_path, sources)
    c["retained_versions"] = 4
    first = helpers["build"](c, offline=True, lexical_only=True)
    assert not first["graph"]["analysis_limited"]
    runtime = repo / "src/trpg_state_machine/dnd_runtime.py"
    runtime.write_text(runtime.read_text() + "\n# No semantic change\n")
    same = helpers["build"](c, offline=True, lexical_only=True)
    helpers["oracle"](c, same["version"], tmp_path, "fresh-comment")
    unit = repo / "src/trpg_state_machine/item_units.py"
    unit.write_text(unit.read_text().replace("2**63 - 1", "2**62 - 1", 1))
    updated = helpers["build"](c, offline=True, lexical_only=True)
    helpers["oracle"](c, updated["version"], tmp_path, "fresh-value")
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph", scope
    assert scope["reason"] == "open-receiver-source-coverage-unavailable", scope


def test_unselected_opaque_method_does_not_reject_unrelated_function_edit(tmp_path, monkeypatch):
    worker = helpers["WORKER"] + "\nclass Opaque:\n    def ignored(self): self.client.work()\n"
    c, repo = helpers["fixture"](tmp_path, {
        "caller.py": helpers["CALLER"], "worker.py": worker,
        "idle.py": "def untouched(): return 1\n"})
    helpers["build"](c, offline=True, lexical_only=True)
    (repo / "src/idle.py").write_text("def untouched(): return 2\n")
    queries = []
    original = Analyzer.query
    def observe(self, scope, expr, **kwargs):
        queries.append(self.nodes[scope]["qualname"])
        return original(self, scope, expr, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Analyzer, "query", observe)
        updated = helpers["build"](c, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert not any(":function:Opaque.ignored#" in owner for owner in scope["selected_owner_ids"])
    assert "Opaque.ignored" not in queries
    helpers["oracle"](c, updated["version"], tmp_path)


def test_recorded_parameter_origin_dependency_requires_receiver_fallback(tmp_path):
    worker = helpers["WORKER"] + "\nclass Opaque:\n    def ignored(self): self.client.work()\n"
    c, repo = helpers["fixture"](tmp_path, {
        "caller.py": helpers["CALLER"], "worker.py": worker})
    first = helpers["build"](c, offline=True, lexical_only=True)
    folder, _ = helpers["manifest"](c, first["version"])
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        reads = list(db.execute("select owner,producer,kind from unit_analysis_reads"))
    assert any(":function:Opaque.ignored#" in owner and "caller.py:module:" in producer
               and kind == "parameter-origin" for owner, producer, kind in reads)
    (repo / "src/caller.py").write_text(
        helpers["CALLER"].replace("execute(first)", "execute(second)"))
    updated = helpers["build"](c, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph", scope
    assert scope["reason"] == "open-receiver-source-coverage-unavailable", scope
    helpers["oracle"](c, updated["version"], tmp_path)


def test_open_receiver_without_field_receipt_does_not_crash_guard(tmp_path):
    c, repo = helpers["fixture"](tmp_path, {
        "opaque.py": "class Opaque:\n    def direct(self): self()\n",
        "idle.py": "def untouched(): return 1\n"})
    first = helpers["build"](c, offline=True, lexical_only=True)
    folder, _ = helpers["manifest"](c, first["version"])
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for raw, in db.execute("select data from sites")]
    assert any("open-receiver-input" in site["unresolved_reasons"] and
               site["resolution_decision"]["write_source_coverage"] is None
               for site in sites)
    (repo / "src/idle.py").write_text("def untouched(): return 2\n")
    updated = helpers["build"](c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    helpers["oracle"](c, updated["version"], tmp_path)
