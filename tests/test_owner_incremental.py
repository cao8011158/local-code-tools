"""Developer controls for immutable owner updates and conservative fallback."""

import ast
import json
import sqlite3

import pytest

from lct.storage import build, current, manifest
from lct.python_analysis import Analyzer
from lct import unit_evidence
from tests.synthetic_support import initialize


def fixture(tmp_path, sources):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for name, source in sources.items():
        (repo / "src" / name).write_text(source)
    return config, repo


def sites(config, version):
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        return [json.loads(raw) for (raw,) in db.execute("select data from sites")]


def test_two_owner_updates_retain_open_callback_reason(tmp_path):
    caller = "from worker import execute\ndef first() -> int: return 1\ndef second() -> int: return 2\ndef run(): execute(first)\n"
    worker = "def execute(callback): callback()\ndef unrelated(v: int): return v\n"
    config, repo = fixture(tmp_path, {"caller.py": caller, "worker.py": worker})
    first = build(config, offline=True, lexical_only=True)
    path = repo / "src/caller.py"
    for source, target in (("first", "second"), ("second", "first")):
        path.write_text(path.read_text().replace(f"execute({source})", f"execute({target})"))
        updated = build(config, offline=True, lexical_only=True)
        scope = updated["incremental"]["analysis_scope"]
        assert scope["mode"] == "incremental-owners"
        assert scope["selected_owner_count"] < scope["selected_owner_count"] + scope["reused_owner_count"]
        callback = next(s for s in sites(config, updated["version"])
                        if s["expression"] == "callback")
        assert any(t.endswith(f":function:{target}#1.1") for t in callback["targets"])
        assert callback["unknown_origin"] is True  # open-project input remains explicit
    assert current(config) == updated["version"]
    assert first["version"] != updated["version"]


@pytest.mark.parametrize("damage", ["schema", "payload"])
def test_missing_or_corrupt_owner_ast_cache_rebuilds(tmp_path, damage):
    config, repo = fixture(tmp_path, {
        "one.py": "def work(v: int): return v + 1\n",
        "two.py": "def idle(v: int): return v\n"})
    first = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, first["version"])
    if damage == "schema":
        meta["unit_ast_cache_schema"] = 999
        (folder / "summary.json").write_text(json.dumps(meta))
    else:
        with sqlite3.connect(folder / "graph-sites.sqlite") as db:
            db.execute("update unit_ast_cache set payload=?", (b"corrupt",))
    (repo / "src/one.py").write_text("def work(v: int): return v + 2\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert current(config) == updated["version"]


@pytest.mark.parametrize("change", ["del worker.unrelated", "worker.unrelated += worker.execute",
                                          "worker.registry.update({'go': worker.execute})"])
def test_changed_mutation_never_uses_unobserved_old_dependency_as_proof(tmp_path, change):
    config, repo = fixture(tmp_path, {
        "writer.py": "import worker\ndef mutate(): return None\n",
        "worker.py": "registry={}\ndef execute(callback): callback()\ndef unrelated(): pass\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/writer.py").write_text("import worker\ndef mutate(): " + change + "\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] in {
        "incremental-owners", "full-graph"}
    if ".update" in change:
        assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"


def test_new_callee_requires_another_actual_analysis_pass(tmp_path):
    source = ("def first(cb): cb()\ndef second(cb): cb()\n"
              "def target() -> int: return 1\ndef run(): first(target)\n")
    config, repo = fixture(tmp_path, {"owner.py": source,
                                      "idle.py": "def unrelated(x: int): return x\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/owner.py").write_text(source.replace("first(target)", "second(target)"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    # This file-seeded route already selects both callees in the first pass.
    assert scope["owner_analysis_iterations"] >= 1
    assert any(ident.endswith(":function:second#1.1")
               for ident in scope["selected_owner_ids"])
    assert scope["owner_jedi_queries_executed"] == updated["graph"]["jedi_queries_executed"]
    assert scope["owner_association_evaluations"] == updated["graph"]["association_evaluations"]


def test_partial_dictionary_evidence_does_not_claim_complete(tmp_path):
    config, repo = fixture(tmp_path, {
        "provider.py": "def first() -> int: return 1\ndef second() -> int: return 2\nregistry={'go':first}\n",
        "consumer.py": "from provider import registry\ndef run(): registry['go']()\n"})
    old = build(config, offline=True, lexical_only=True)
    assert old["value_flow_coverage"] == "partial"
    (repo / "src/provider.py").write_text(
        "def first() -> int: return 1\ndef second() -> int: return 2\nregistry={'go':second}\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert updated["value_flow_coverage"] == "partial"


def test_owner_update_replaces_source_observations_exactly(tmp_path):
    config, repo = fixture(tmp_path, {
        "caller.py": "from worker import execute\ndef first(): pass\ndef second(): pass\n"
                     "def run(): execute(first)\n",
        "worker.py": "def execute(callback): callback()\ndef idle(): pass\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/caller.py").write_text((repo / "src/caller.py").read_text().replace(
        "execute(first)", "execute(second)"))
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    alternate = dict(config, data=str(tmp_path / "fresh"))
    full = build(alternate, offline=True, lexical_only=True)
    def observations(c, version):
        folder, meta = manifest(c, version)
        with sqlite3.connect(folder / "graph-sites.sqlite") as db:
            tables = {}
            for table in ("unit_source_supports", "unit_container_subscriptions",
                          "unit_container_writes"):
                tables[table] = sorted((json.loads(raw) for (raw,) in db.execute(
                    f"select data from {table}")), key=lambda r: json.dumps(r, sort_keys=True))
        return tables, tuple(meta[key] for key in (
            "origin_dependency_schema", "origin_dependency_coverage",
            "origin_support_count", "origin_subscription_count", "origin_write_count"))
    assert observations(config, updated["version"]) == observations(alternate, full["version"])


def test_two_pass_owner_expansion_reuses_capture_and_counts_actual_work(tmp_path, monkeypatch):
    config, repo = fixture(tmp_path, {
        "a.py": "from b import first,second\ndef target(): pass\ndef run(): first(target)\n",
        "b.py": "def first(cb): cb()\ndef second(cb): cb()\ndef idle(): pass\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text(
        "from b import first,second\ndef target(): pass\ndef run(): second(target)\n")
    inventory = []
    original = Analyzer.inventory
    def counted(self, obj, lexical, execution, phase, deferred):
        if isinstance(obj, ast.Module):
            inventory.append(lexical)
        return original(self, obj, lexical, execution, phase, deferred)
    monkeypatch.setattr(Analyzer, "inventory", counted)
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["owner_analysis_iterations"] == 2
    assert len(inventory) == len(set(inventory)) == 2
    assert scope["owner_jedi_queries_executed"] == updated["graph"]["jedi_queries_executed"]
    assert scope["owner_association_evaluations"] == updated["graph"]["association_evaluations"]


def test_ast_cache_preserves_module_and_definition_object_identity():
    module = ast.parse("def run(callback): callback()\n")
    module._lct_source = "def run(callback): callback()\n"
    original = {"module": module, "function": module.body[0]}
    restored = unit_evidence._decode_asts(unit_evidence._encode_asts(original))
    assert restored["module"].body[0] is restored["function"]
    assert restored["module"]._lct_source == module._lct_source


def test_unresolved_attribute_receiver_falls_back_with_reason(tmp_path):
    config, repo = fixture(tmp_path, {
        "a.py": "import b\ndef change(): pass\n",
        "b.py": "def callback(): pass\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text("import b\ndef change(obj): obj.callback = b.callback\n")
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph"
    assert scope["reason"] == "changed-writer-origin-unresolved"


@pytest.mark.parametrize("writer", [
    "from provider import registry\ndef change(registry): registry['go']=second\n",
    "from provider import registry\nfrom other import registry\ndef change(): registry['go']=second\n",
    "from provider import registry\ndef change(flag):\n"
    "    if flag: registry={}\n    registry['go']=second\n",
    "from provider import registry\ndef change():\n"
    "    registry['go']=second\n    registry={}\n",
])
def test_ambiguous_new_writer_receiver_never_chooses_first_binding(tmp_path, writer):
    config, repo = fixture(tmp_path, {
        "provider.py": "def first(): pass\nregistry={'go':first}\n",
        "other.py": "registry={}\n",
        "writer.py": "from provider import registry\ndef change(): pass\n"})
    build(config, offline=True, lexical_only=True)
    (repo / "src/writer.py").write_text("second=None\n" + writer)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert updated["incremental"]["analysis_scope"]["reason"] in {
        "changed-writer-origin-unresolved", "changed-opaque-call-effect-unavailable"}


def test_closed_world_consecutive_callback_retargets_match_fresh(tmp_path):
    config, repo = fixture(tmp_path, {
        "a.py": "from b import first,second\ndef target(): pass\ndef run(): first(target)\n",
        "b.py": "def first(cb): cb()\ndef second(cb): cb()\ndef idle(): pass\n"})
    config["repositories"][0]["closed_world"] = True
    build(config, offline=True, lexical_only=True)
    caller = repo / "src/a.py"
    for current_name, next_name in (("first", "second"), ("second", "first")):
        caller.write_text(caller.read_text().replace(
            f"{current_name}(target)", f"{next_name}(target)"))
        updated = build(config, offline=True, lexical_only=True)
        scope = updated["incremental"]["analysis_scope"]
        assert scope["mode"] == "incremental-owners"
        assert scope["owner_analysis_iterations"] >= 1
        full_config = dict(config, data=str(tmp_path / ("fresh-" + next_name)))
        full = build(full_config, offline=True, lexical_only=True)
        assert sites(config, updated["version"]) == sites(full_config, full["version"])
        def origins(c, version):
            folder, _ = manifest(c, version)
            with sqlite3.connect(folder / "graph-sites.sqlite") as db:
                return {table: sorted(raw for (raw,) in db.execute(
                    "select data from " + table)) for table in
                    ("unit_source_supports", "unit_container_subscriptions",
                     "unit_container_writes")}
        assert origins(config, updated["version"]) == origins(full_config, full["version"])


def test_candidate_scope_changes_reobserve_retained_owners_in_both_directions(tmp_path):
    caller = "from b import run\ndef invoke():\n    run()\n"
    config, repo = fixture(tmp_path, {
        "a.py": "def first(): pass\n",
        "b.py": "from a import first\ndef run():\n    first()\n",
        "c.py": caller,
        "spare.py": "def idle(): pass\ndef run(): idle()\n"})
    build(config, offline=True, lexical_only=True)
    source = repo / "src/c.py"
    for step, changed in enumerate((
            "from missing_provider import run\ndef invoke():\n    run()\n", caller)):
        source.write_text(changed)
        updated = build(config, offline=True, lexical_only=True)
        assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners", updated["incremental"]["analysis_scope"]
        fresh_config = dict(config, data=str(tmp_path / f"fresh-scope-{step}"))
        full = build(fresh_config, offline=True, lexical_only=True)
        assert sites(config, updated["version"]) == sites(fresh_config, full["version"])
        for table in ("analysis_input_scopes", "analysis_input_members",
                      "analysis_input_consumers", "import_requests"):
            def records(c, version):
                folder, _ = manifest(c, version)
                with sqlite3.connect(folder / "graph-sites.sqlite") as db:
                    return list(db.execute("select * from " + table + " order by 1"))
            assert records(config, updated["version"]) == records(
                fresh_config, full["version"]), table


@pytest.mark.parametrize("other_importer", [False, True])
def test_unresolved_import_lookup_keeps_only_current_importer_support(
        tmp_path, other_importer):
    sources = {"a.py": "from b import missing\n", "b.py": "def foo(): pass\n",
               "c.py": "def foo(): pass\n"}
    if other_importer:
        sources["d.py"] = "from b import missing\n"
    config, repo = fixture(tmp_path, sources)
    build(config, offline=True, lexical_only=True)
    for step, module in enumerate(("c", "b")):
        (repo / "src/a.py").write_text(f"from {module} import missing\n")
        updated = build(config, offline=True, lexical_only=True)
        assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        fresh_config = dict(config, data=str(tmp_path / f"fresh-lookup-{step}"))
        full = build(fresh_config, offline=True, lexical_only=True)
        def edges(c, version):
            folder, _ = manifest(c, version)
            with sqlite3.connect(folder / "catalog.sqlite") as db:
                return sorted(raw for (raw,) in db.execute("select data from edges"))
        assert edges(config, updated["version"]) == edges(fresh_config, full["version"])
        lookups = [json.loads(raw) for raw in edges(config, updated["version"])
                   if json.loads(raw)["kind"] == "LOOKUP_IN"]
        expected = {module, "b"} if other_importer else {module}
        assert {e["lookup"]["module"] for e in lookups} == expected
