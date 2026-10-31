"""Independent captured-query scope persistence, reuse and indexed locality."""
import ast
import sqlite3

import pytest

from lct.common import ToolError, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.simple_python import component_policy
from lct.storage import FileDependencies, build, current, manifest
from tests.synthetic_support import initialize
from test_common_certificate_independent import records as old_records


def setup(tmp_path, noise=0, opaque=False):
    config, repo = initialize(tmp_path / "input-scope")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    sources = {
        "pkg/provider.py": "def marker(): return 'old'\n",
        "pkg/client.py": ("from .provider import marker\n"
                          "def use(callback):\n    callback()\n    callback()\n"),
    }
    if opaque:
        sources["pkg/client.py"] = "def use(*callbacks):\n    missing()\n"
    for i in range(noise):
        sources[f"other_{i}/provider.py"] = f"def marker(): return {i}\n"
        sources[f"other_{i}/client.py"] = "from .provider import marker\ndef run(): marker()\n"
    for path, source in sources.items():
        target = repo / "src" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    return config, repo


def records(config, version):
    result = old_records(config, version)
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        for table in ("analysis_input_scopes", "analysis_input_members", "analysis_input_consumers"):
            result[table] = sorted(tuple(r) for r in db.execute(f"select * from {table}"))
    return result


@pytest.mark.parametrize("noise", [0, 20])
def test_negative_query_scope_is_used_by_update_and_matches_full(tmp_path, monkeypatch, noise):
    import lct.extract as extraction
    config, repo = setup(tmp_path, noise)
    first = build(config, offline=True, lexical_only=True)
    assert first.get("analysis_input_schema") == 1
    assert first["analysis_input_coverage"] == "captured-query-scopes-partial"
    assert first["analysis_input_truncated"] is False
    before = records(config, first["version"])
    folder, metadata = manifest(config, first["version"])
    repository = config["repositories"][0]["name"]
    with FileDependencies(folder, metadata) as dependencies:
        assert dependencies.input_scope_readers(repository, "src/pkg/provider.py") == {
            (repository, "src/pkg/client.py")}
        assert dependencies.input_scope_watchers() == set()
    actual_readers = FileDependencies.input_scope_readers
    selected, parsed = [], []
    def readers(self, repository, path):
        selected.append((repository, path))
        return actual_readers(self, repository, path)
    actual_extract = extraction.python_nodes
    def parse(file):
        parsed.append(file["path"])
        return actual_extract(file)
    monkeypatch.setattr(FileDependencies, "input_scope_readers", readers)
    monkeypatch.setattr(extraction, "python_nodes", parse)
    provider = repo / "src/pkg/provider.py"
    provider.write_text(provider.read_text().replace("'old'", "'changed'"))
    with pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == first["version"] and records(config, first["version"]) == before
    parsed.clear()
    selected.clear()
    updated = build(config, offline=True, lexical_only=True)
    assert set(parsed) == {"src/pkg/provider.py", "src/pkg/client.py"} and len(parsed) == 2
    assert (repository, "src/pkg/provider.py") in selected
    assert updated["incremental"]["analysis_scope"]["mode"] == "certified-simple-python-component"
    assert updated["incremental"]["analysis_scope"]["reused_python_files"] == 2 * noise
    assert records(config, first["version"]) == before
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(fresh_config, fresh["version"])
    parsed.clear()
    same = build(config, offline=True, lexical_only=True)
    assert parsed == [] and records(config, same["version"]) == records(config, updated["version"])


def analyzer_for(config):
    files, repos, _ = inventory(config)
    nodes, asts = extract(files)
    graph = Graph(nodes, asts, repos)
    policy = component_policy(files, asts, graph)
    analyzer = Analyzer(graph.nodes, asts, repos, graph.imported, candidate_components=policy)
    scope = next(n["node_id"] for n in nodes if n.get("qualname") == "use")
    expressions = [n.func for n in ast.walk(asts[scope]) if isinstance(n, ast.Call)]
    return analyzer, scope, expressions, policy


def test_real_empty_query_and_cache_do_not_reenumerate_scope(tmp_path):
    config, _ = setup(tmp_path)
    analyzer, scope, expressions, policy = analyzer_for(config)
    try:
        first = analyzer.query(scope, expressions[0])
        assert "jedi-no-result" in first.reasons
        assert hasattr(analyzer, "analysis_inputs")
        footprint = analyzer.analysis_inputs.export()
        assert len(footprint["scopes"]) == 1 and len(footprint["members"]) == 2
        assert len(footprint["consumers"]) == 1 and not footprint["truncated"]
        class AlreadyRegistered(frozenset):
            def __iter__(self):
                raise AssertionError("same context members enumerated again")
        for module, component in list(policy.items()):
            policy[module] = AlreadyRegistered(component)
        executions = analyzer.executed_queries
        assert analyzer.query(scope, expressions[0]) == first
        assert analyzer.executed_queries == executions
        analyzer.query(scope, expressions[1])
        assert analyzer.analysis_inputs.export() == footprint
    finally:
        analyzer.close()


def test_jedi_exception_still_records_its_input_scope(tmp_path, monkeypatch):
    config, _ = setup(tmp_path)
    analyzer, scope, expressions, _ = analyzer_for(config)
    try:
        def failed(*args, **kwargs):
            raise RuntimeError("independent injected backend failure")
        monkeypatch.setattr(analyzer.scripts[analyzer.module_for[scope]], "infer", failed)
        result = analyzer.query(scope, expressions[0])
        assert "jedi-error:RuntimeError" in result.reasons
        assert hasattr(analyzer, "analysis_inputs")
        footprint = analyzer.analysis_inputs.export()
        assert len(footprint["members"]) == 2 and len(footprint["consumers"]) == 1
    finally:
        analyzer.close()


def test_uncertified_capture_uses_explicit_wide_scope(tmp_path):
    config, _ = setup(tmp_path, opaque=True)
    built = build(config, offline=True, lexical_only=True)
    assert built.get("analysis_input_schema") == 1
    assert built["simple_python_certificate"] is None
    folder, metadata = manifest(config, built["version"])
    repository = config["repositories"][0]["name"]
    with FileDependencies(folder, metadata) as dependencies:
        assert dependencies.input_scope_watchers() == {(repository, "src/pkg/client.py")}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        assert list(db.execute("select kind from analysis_input_scopes")) == [("capture",)]
        assert db.execute("select count(*) from analysis_input_members").fetchone()[0] == 0


def test_shared_scope_does_not_repeat_members_or_global_size_walk():
    from lct.analysis_inputs import AnalysisInputs
    modules = {f"m{i}": dict(repository="repo", path=f"{i}.py") for i in range(100)}
    ledger = AnalysisInputs(modules)
    class PreparedComponent(frozenset):
        blocked = False
        def __iter__(self):
            if self.blocked:
                raise AssertionError("prepared component rescanned")
            return super().__iter__()
    class NoGlobalSizeWalk(dict):
        def values(self):
            raise AssertionError("all scope sizes revisited for one consumer")
    component = PreparedComponent(modules)
    ledger.observe("m0", component)
    component.blocked = True
    ledger.members = NoGlobalSizeWalk(ledger.members)
    for module in modules:
        ledger.observe(module, component)
    payload = ledger.export()
    assert len(payload["scopes"]) == 1 and len(payload["members"]) == 100
    assert len(payload["consumers"]) == 100 and not payload["truncated"]


def test_merging_independent_scopes_does_not_rescan_scope_catalog_per_consumer():
    from lct.analysis_inputs import AnalysisInputs, merge
    modules = {f"m{i}": dict(repository="repo", path=f"{i}.py") for i in range(80)}
    ledger = AnalysisInputs(modules)
    for module in modules:
        ledger.observe(module, frozenset({module}))
    payload = ledger.export()
    class CountIterations(list):
        scans = 0
        def __iter__(self):
            self.scans += 1
            return super().__iter__()
    catalog = CountIterations(payload["scopes"])
    payload["scopes"] = catalog
    merged = merge(payload, dict(scopes=[], members=[], consumers=[], truncated=False),
                   selected=set(), old_nodes=modules, new_nodes=modules,
                   verified={('repo', n['path']) for n in modules.values()})
    assert merged is not None and len(merged["scopes"]) == 80
    assert catalog.scans <= 3


def test_input_scope_lookup_is_indexed_under_unrelated_scope_growth(tmp_path):
    measurements = []
    for noise in (0, 20):
        config, _ = setup(tmp_path / str(noise), noise)
        built = build(config, offline=True, lexical_only=True)
        assert built.get("analysis_input_schema") == 1
        folder, metadata = manifest(config, built["version"])
        repository = config["repositories"][0]["name"]
        with FileDependencies(folder, metadata) as dependencies:
            probes = []
            for _ in range(3):
                traces, steps = [], [0]
                def tick():
                    steps[0] += 1
                    return 0
                dependencies.db.set_trace_callback(traces.append)
                dependencies.db.set_progress_handler(tick, 1)
                try:
                    found = dependencies.input_scope_readers(repository, "src/pkg/provider.py")
                finally:
                    dependencies.db.set_trace_callback(None)
                    dependencies.db.set_progress_handler(None, 0)
                assert found == {(repository, "src/pkg/client.py")} and len(traces) == 1
                plan = list(dependencies.db.execute("explain query plan " + traces[0]))
                assert not any("SCAN" in row[3] for row in plan), plan
                assert sum("SEARCH" in row[3] and "INDEX" in row[3] for row in plan) >= 2, plan
                probes.append(steps[0])
            assert probes[1] == probes[2]
            measurements.append(probes)
    assert measurements[0] == measurements[1]
