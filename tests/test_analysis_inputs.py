"""Captured query input scopes are bounded, indexed and preserved locally."""
import sqlite3

import pytest
from lct.common import ToolError

from lct.analysis_inputs import AnalysisInputs
from lct.analysis_inputs import valid as valid_inputs
from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.storage import build, current, manifest, FileDependencies
from tests.test_common_python_certificate import setup as common_setup


def test_ledger_component_deduplicates_and_atomically_truncates():
    modules = {f"m{i}": dict(repository="r", path=f"m{i}.py") for i in range(4)}
    ledger = AnalysisInputs(modules, limit=7)
    group = frozenset({"m0", "m1"})
    ledger.observe("m0", group)
    first = ledger.export()
    ledger.observe("m0", group)
    assert ledger.export() == first
    ledger.observe("m1", group)
    assert len(ledger.export()["scopes"]) == 1
    assert len(ledger.export()["members"]) == 2
    assert len(ledger.export()["consumers"]) == 2
    ledger.observe("m2", frozenset({"m2", "m3"}))
    assert ledger.export()["truncated"] is True
    assert len(ledger.export()["scopes"]) == 1  # no partial second scope


def test_component_members_inspected_once_for_many_consumers():
    class GuardFrozenset(frozenset):
        blocked = False
        def __iter__(self):
            if self.blocked:
                raise AssertionError("component members re-enumerated")
            return super().__iter__()
    modules = {f"m{i}": dict(repository="r", path=f"m{i}.py") for i in range(200)}
    component = GuardFrozenset(modules)
    ledger = AnalysisInputs(modules)
    ledger.observe("m0", component)
    component.blocked = True
    ledger.observe("m0", component)
    for i in range(1, 200):
        ledger.observe(f"m{i}", component)
    assert not ledger.truncated
    assert len(ledger.scopes) + ledger.member_count + len(ledger.consumers) == 401


def test_query_empty_error_and_cache_observe_same_capture_scope(tmp_path):
    source = "def f():\n    missing()\n"
    nodes, trees = python_nodes(dict(repository="r", path="a.py", text=source,
                                     sha256=digest(source), is_test=False))
    graph = Graph(nodes, trees, [dict(name="r", path=str(tmp_path), head="captured")])
    analyzer = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    try:
        site = next(s for s in analyzer.sites if s["expression"] == "missing")
        module = analyzer.module_for[site["execution_owner"]]
        class Empty:
            def infer(self, *_): return []
        analyzer.scripts[module] = Empty()
        result = analyzer.query(site["execution_owner"], site["_expr"])
        assert "jedi-no-result" in result.reasons
        first = analyzer.analysis_inputs.export()
        assert first["scopes"] == [dict(id="capture:all-captured-python", kind="capture")]
        analyzer.query(site["execution_owner"], site["_expr"])
        assert analyzer.analysis_inputs.export() == first
        class Fail:
            def infer(self, *_): raise RuntimeError("injected")
        analyzer.scripts[module] = Fail()
        analyzer.queries.clear()
        assert "jedi-error:RuntimeError" in analyzer.query(
            site["execution_owner"], site["_expr"]).reasons
        assert analyzer.analysis_inputs.export() == first
    finally:
        analyzer.close()


@pytest.mark.parametrize("noise", [0, 20])
def test_persisted_scope_reader_and_local_full_equality(tmp_path, noise):
    config, repo, target = common_setup(tmp_path, noise)
    first = build(config, offline=True, lexical_only=True)
    folder, metadata = manifest(config, first["version"])
    assert metadata["analysis_input_schema"] == 1
    assert metadata["analysis_input_coverage"] == "captured-query-scopes-partial"
    with FileDependencies(folder, metadata) as deps:
        assert deps.input_scope_readers("synthetic-review", "src/trpg_state_machine/availability.py") == {
            ("synthetic-review", "src/trpg_state_machine/availability.py")}
        assert deps.input_scope_watchers() == set()
        plan = list(deps.db.execute("explain query plan select scope_id from analysis_input_members "
                                    "where repository=? and path=?", (
                                    "synthetic-review", "src/trpg_state_machine/availability.py")))
        assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plan)
    old = _records(folder)
    module = target / "availability.py"
    module.write_bytes(module.read_bytes().replace(b"context=context", b"context=None"))
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "certified-simple-python-component"
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert _records(manifest(config, updated["version"])[0]) == _records(manifest(fresh_config, fresh["version"])[0])
    assert _records(folder) == old and current(config) == updated["version"]


def test_scope_manifest_and_truncation_fail_closed(tmp_path):
    config, _, _ = common_setup(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    folder, metadata = manifest(config, first["version"])
    with FileDependencies(folder, metadata) as deps:
        assert deps.input_scope_watchers() == set()
    for change in ({"analysis_input_schema": 99},
                   {"analysis_input_scope_count": metadata["analysis_input_scope_count"] + 1}):
        with pytest.raises(ToolError):
            FileDependencies(folder, dict(metadata, **change))
    with FileDependencies(folder, dict(metadata, analysis_input_truncated=True)) as deps:
        with pytest.raises(ToolError):
            deps.input_scope_readers("synthetic-review", "src/trpg_state_machine/availability.py")
    from lct.python_incremental import prepare
    assert prepare(None, dict(metadata, analysis_input_schema=None), [], [],
                   dependencies=None, graph_sites=None) == (
                       None, "previous-analysis-input-evidence-unavailable")


def test_identical_capture_preserves_scope_rows(tmp_path):
    config, _, _ = common_setup(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    initial = _records(manifest(config, first["version"])[0])
    second = build(config, offline=True, lexical_only=True)
    assert second["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert _records(manifest(config, second["version"])[0]) == initial


def test_validator_fetches_only_ledger_module_columns_and_ids(tmp_path, monkeypatch):
    config, _, _ = common_setup(tmp_path, 20)
    first = build(config, offline=True, lexical_only=True)
    folder, metadata = manifest(config, first["version"])
    import lct.storage as storage
    original = storage.sqlite3.connect
    observed = []
    class CatalogConnection:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, sql, args=()):
            observed.append((sql, tuple(args)))
            assert "data" not in sql.lower() and "where node_id in" in sql.lower()
            return self.connection.execute(sql, args)
        def close(self):
            self.connection.close()
    def connect(path, *args, **kwargs):
        connection = original(path, *args, **kwargs)
        return CatalogConnection(connection) if "catalog.sqlite" in str(path) else connection
    monkeypatch.setattr(storage.sqlite3, "connect", connect)
    with FileDependencies(folder, metadata) as deps:
        needed = set(deps.db.execute("select module_id from analysis_input_members union "
                                     "select module_id from analysis_input_consumers"))
    assert observed and all(len(args) <= 256 for _, args in observed)
    assert {ident for _, args in observed for ident in args} == {row[0] for row in needed}
    assert not valid_inputs(dict(scopes=[dict(id="capture:all-captured-python", kind="capture")],
                                 members=[], consumers=[dict(scope_id="capture:all-captured-python",
                                                            module_id="unknown", repository="r", path="x.py")]), {})


def _records(folder):
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        return {table: list(db.execute(f"select * from {table} order by 1,2"))
                for table in ("analysis_input_scopes", "analysis_input_members",
                              "analysis_input_consumers")}
