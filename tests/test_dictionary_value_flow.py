"""Public-build controls for private, indexed dictionary value evidence."""

import ast
import json
import sqlite3
from types import SimpleNamespace

import pytest

from lct.common import ToolError
from lct.python_analysis import Analyzer
from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def setup(tmp_path, a, b, noise=0):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/a.py").write_text(a)
    (repo / "src/b.py").write_text(b)
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"def idle_{i}(): pass\n")
    return config, repo


def test_container_entry_call_edges_and_exact_reverse_lookup(tmp_path):
    c, repo = setup(tmp_path, ("def first(): pass\ndef second(): pass\n"
                               "one={'go':first}\ntwo={'go':second}\n"),
                    "from a import one,two\ndef run():\n one['go']()\n two['go']()\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    assert meta["value_flow_coverage"] == "certified-dictionary-v1"
    assert meta["value_flow_projection"] == "internal-sqlite-only"
    with FileDependencies(folder, meta) as deps:
        entries = deps.entry_ids_for_file("synthetic-review", "src/a.py")
        assert len(entries) == 2
        records = deps.get_value_nodes(sorted(entries))
        assert len({r["container"] for r in records}) == 2
        assert {r["key"] for r in records} == {"go"}
        for entry in entries:
            assert deps.value_readers(entry) == {("synthetic-review", "src/b.py")}
            incoming = deps.get_value_relations(entry, "in")
            assert not incoming["has_more"]
            assert {e["kind"] for e in incoming["relations"]} == {"ADDRESSES", "WRITES", "READS"}
            container = next(r["container"] for r in records if r["id"] == entry)
            bound = deps.get_value_relations(container, "in")["relations"]
            assert {e["kind"] for e in bound} == {"BINDS"}
            assert len(bound) == 2  # declaration and imported binding
            for relation in bound:
                binder = deps.get_value_nodes([relation["source"]])[0]
                assert binder["kind"] == "binding"
                assert binder["name"] in {"one", "two"}
            read = next(e["source"] for e in incoming["relations"] if e["kind"] == "READS")
            assert "USES_BINDING" in {e["kind"] for e in
                                      deps.get_value_relations(read)["relations"]}
        assert deps.get_value_nodes(["missing"]) == []
        with pytest.raises(ToolError):
            deps.get_value_nodes(["missing"] * 101)
        with sqlite3.connect(folder / "graph-sites.sqlite") as db:
            plan = list(db.execute("explain query plan select consumer_repository,consumer_path "
                                   "from value_reads where entry=?", (next(iter(entries)),)))
            assert any("INDEX" in str(row) for row in plan), plan
    identical = build(c, offline=True, lexical_only=True)
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    same_folder, same_meta = manifest(c, identical["version"])
    with FileDependencies(same_folder, same_meta) as deps:
        assert deps.entry_ids_for_file("synthetic-review", "src/a.py") == entries


def test_negative_entry_and_bounded_relation_page(tmp_path):
    items = ",".join(f"'{i}':target" for i in range(105))
    c, _ = setup(tmp_path, f"def target(): pass\nregistry={{{items}}}\n",
                 "from a import registry\ndef run(): registry['missing']()\n")
    meta = build(c, offline=True, lexical_only=True)
    folder, summary = manifest(c, meta["version"])
    with FileDependencies(folder, summary) as deps:
        entries = deps.entry_ids_for_file("synthetic-review", "src/a.py")
        assert len(entries) == 106
        absent = [r for e in entries for r in deps.get_value_nodes([e]) if not r["present"]]
        assert len(absent) == 1 and absent[0]["key"] == "missing"
        assert deps.value_readers(absent[0]["id"]) == {("synthetic-review", "src/b.py")}
        container = absent[0]["container"]
        page = deps.get_value_relations(container, limit=100)
        assert len(page["relations"]) == 100 and page["has_more"]
        with pytest.raises(ToolError):
            deps.get_value_relations(container, limit=101)


def test_unrelated_producer_only_dictionary_retained_without_reparse(tmp_path, monkeypatch):
    from lct import extract as extraction

    c, repo = setup(tmp_path,
                    "def first(): pass\ndef second(): pass\nregistry={'go':first}\n",
                    "from a import registry\ndef run(): registry['go']()\n")
    (repo / "src/elsewhere.py").write_text(
        "def unrelated(): pass\nother={'same':unrelated}\n")
    first = build(c, offline=True, lexical_only=True)
    folder, prior = manifest(c, first["version"])
    with FileDependencies(folder, prior) as deps:
        previous = deps.entry_ids_for_file("synthetic-review", "src/elsewhere.py")
    assert len(previous) == 1
    parsed = []
    watcher_queries = []
    original = extraction.python_nodes
    original_watchers = FileDependencies.analysis_watchers

    def count(file):
        parsed.append(file["path"])
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", count)
    def watched(self, kind):
        watcher_queries.append(kind)
        return original_watchers(self, kind)

    monkeypatch.setattr(FileDependencies, "analysis_watchers", watched)
    (repo / "src/a.py").write_text(
        "def first(): pass\ndef second(): pass\nregistry={'go':second}\n")
    second = build(c, offline=True, lexical_only=True)
    assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(parsed) == ["src/a.py"]
    assert watcher_queries == []  # owner path uses the indexed same-origin subscriptions
    next_folder, summary = manifest(c, second["version"])
    with FileDependencies(next_folder, summary) as deps:
        assert deps.entry_ids_for_file("synthetic-review", "src/elsewhere.py") == previous


def test_association_trace_sibling_order_is_source_stable():
    expr = ast.parse("target", mode="eval").body
    expr.lineno = 1
    expr.col_offset = 0
    root = ("scope", id(expr), (1, 0))
    early, late = ("scope", 1, (2, 0)), ("scope", 2, (4, 0))
    traces = {root: dict(scope="scope", path="a.py", line=1, column=0,
                         expression="target", rule="Root"),
              early: dict(scope="scope", path="a.py", line=2, column=0,
                          expression="first", rule="Name"),
              late: dict(scope="scope", path="a.py", line=4, column=0,
                         expression="second", rule="Name")}
    outputs = []
    for order in ([late, early], [early, late]):
        fake = SimpleNamespace(traces=traces, dependencies={root: order})
        outputs.append(Analyzer.explain(fake, "scope", expr))
    assert outputs[0] == outputs[1]
    assert [s["line"] for s in outputs[0]["steps"]] == [1, 2, 4]
    assert outputs[0]["truncated"] is False


def test_import_module_and_function_aliases_bind_same_container(tmp_path):
    c, _ = setup(tmp_path, "def target(): pass\nregistry={'go':target}\n",
                 "from a import registry as imported\nalias=imported\n"
                 "def run():\n local=alias\n local['go']()\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    with FileDependencies(folder, meta) as deps:
        entry = next(iter(deps.entry_ids_for_file("synthetic-review", "src/a.py")))
        container = deps.get_value_nodes([entry])[0]["container"]
        binders = deps.get_value_relations(container, "in")["relations"]
        assert {deps.get_value_nodes([e["source"]])[0]["binding_kind"] for e in binders} == {
            "declaration", "import", "module-alias", "local-alias"}
        read = next(e["source"] for e in deps.get_value_relations(entry, "in")["relations"]
                    if e["kind"] == "READS")
        links = deps.get_value_relations(read)["relations"]
        binder = next(e["target"] for e in links if e["kind"] == "USES_BINDING")
        assert deps.get_value_nodes([binder])[0]["name"] == "local"


@pytest.mark.parametrize("missing", ["schema", "coverage"])
def test_old_or_partial_value_evidence_falls_back(tmp_path, missing):
    c, repo = setup(tmp_path, "def target(): pass\nregistry={'go':target}\n",
                    "from a import registry\ndef run(): registry['go']()\n")
    first = build(c, offline=True, lexical_only=True)
    folder, summary = manifest(c, first["version"])
    updated = dict(summary)
    if missing == "schema":
        updated.pop("value_flow_schema")
    else:
        updated["value_flow_coverage"] = "partial"
    (folder / "summary.json").write_text(json.dumps(updated))
    (repo / "src/a.py").write_text(
        "def target(): pass\ndef other(): pass\nregistry={'go':other}\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "full-graph"


def test_record_budget_marks_partial_without_persisting_partial_claim(tmp_path, monkeypatch):
    import lct.value_flow as flow

    monkeypatch.setattr(flow, "LIMIT", 10)
    c, repo = setup(tmp_path, "def target(): pass\nregistry={'go':target}\n",
                 "from a import registry\ndef run(): registry['go']()\n")
    built = build(c, offline=True, lexical_only=True)
    assert built["simple_python_certificate"] is None
    assert built["value_flow_coverage"] == "partial"
    assert built["value_flow_node_count"] == 0
    assert built["graph"]["call_sites"] == 1
    folder, summary = manifest(c, built["version"])
    with FileDependencies(folder, summary) as deps:
        with pytest.raises(ToolError):
            deps.entry_ids_for_file("synthetic-review", "src/a.py")
        with pytest.raises(ToolError):
            deps.value_readers("value:unknown")
    (repo / "src/a.py").write_text(
        "def target(): pass\ndef other(): pass\nregistry={'go':other}\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "full-graph"


def test_reverse_entry_lookup_work_does_not_scale_with_unrelated_producers(tmp_path):
    measurements = []
    for noise in (0, 20):
        c, repo = setup(tmp_path / str(noise),
                        "def target(): pass\nregistry={'go':target}\n",
                        "from a import registry\ndef run(): registry['go']()\n")
        for i in range(noise):
            (repo / f"src/other_{i}.py").write_text(
                f"def target_{i}(): pass\nregistry_{i}={{'go':target_{i}}}\n")
        built = build(c, offline=True, lexical_only=True)
        folder, meta = manifest(c, built["version"])
        with FileDependencies(folder, meta) as deps:
            entry = next(iter(deps.entry_ids_for_file("synthetic-review", "src/a.py")))
            steps = [0]

            def progress():
                steps[0] += 1
                return 0

            deps.db.set_progress_handler(progress, 1)
            try:
                assert deps.value_readers(entry) == {("synthetic-review", "src/b.py")}
            finally:
                deps.db.set_progress_handler(None, 0)
            measurements.append((meta["value_flow_node_count"], steps[0]))
    assert measurements[1][0] > measurements[0][0]
    assert measurements[1][1] == measurements[0][1], measurements


@pytest.mark.parametrize("key_expression", ["True", "1", "1.0", "unknown_key"])
def test_unmodeled_keys_do_not_enter_exact_dictionary_certificate(tmp_path, key_expression):
    c, repo = setup(tmp_path,
                    f"def target(): pass\nregistry={{{key_expression}:target}}\n",
                    "from a import registry\ndef run(): registry[True]()\n")
    build(c, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text(
        f"def target(): pass\ndef another(): pass\nregistry={{{key_expression}:another}}\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "full-graph"
