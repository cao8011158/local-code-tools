"""Independent 4A observations before early exits, caches and failed lookups."""
import shutil
import sqlite3

import pytest

from lct.common import ToolError, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.simple_python import component_policy
from lct.storage import FileDependencies, GRAPH_SITES, build, current, hash_artifact, manifest
from tests.synthetic_support import initialize
from test_analysis_inputs_independent import records


def setup(tmp_path, *, calls=False, noise=0):
    config, repo = initialize(tmp_path / "observations")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    source = {
        "a.py": "def target(value): return value\nclass Box: pass\n",
        "b.py": ("from a import target, Box\ndef use(arg): return " +
                 ("target(arg)\n" if calls else "arg\n")),
    }
    source.update({f"noise_{i}.py": f"def idle_{i}(): return {i}\n" for i in range(noise)})
    for name, text in source.items():
        (repo / "src" / name).write_text(text)
    return config, repo


def analyzer_for(config):
    files, repos, _ = inventory(config)
    nodes, trees = extract(files)
    graph = Graph(nodes, trees, repos)
    policy = component_policy(files, trees, graph)
    return Analyzer(graph.nodes, trees, graph.repos, graph.imported,
                    candidate_components=policy), nodes, trees


def purposes(analyzer, module):
    rows = analyzer.analysis_inputs.export()["consumers"]
    mask = 0
    for row in rows:
        if row["module_id"] == module:
            mask |= row.get("purposes", 0)
    return mask


def ident(nodes, qualname):
    return next(n["node_id"] for n in nodes if n.get("qualname") == qualname)


def test_empty_candidate_universe_is_observed_before_any_jedi(tmp_path):
    config, _ = setup(tmp_path)
    analyzer, nodes, _ = analyzer_for(config)
    try:
        target = ident(nodes, "target")
        assert list(analyzer.candidate_sites(target)) == []
        assert analyzer.executed_queries == 0
        assert purposes(analyzer, analyzer.module_for[target]) & 2 == 2
    finally:
        analyzer.close()


def test_direct_may_call_name_gate_is_observed(tmp_path):
    config, _ = setup(tmp_path, calls=True)
    analyzer, nodes, _ = analyzer_for(config)
    try:
        target = ident(nodes, "target")
        site = next(s for s in analyzer.sites if s["expression"] == "target")
        assert analyzer.may_call(target, site) is True
        assert analyzer.executed_queries == 0
        assert purposes(analyzer, analyzer.module_for[target]) & 2 == 2
    finally:
        analyzer.close()


def test_known_lexical_parameter_records_lookup_without_jedi(tmp_path):
    config, _ = setup(tmp_path)
    analyzer, nodes, trees = analyzer_for(config)
    try:
        scope = ident(nodes, "use")
        anchor = trees[scope].body[0].value
        analyzer.name(scope, "arg", (anchor.lineno, anchor.col_offset), anchor)
        assert analyzer.executed_queries == 0
        assert purposes(analyzer, analyzer.module_for[scope]) & 4 == 4
    finally:
        analyzer.close()


def test_absent_member_records_observation_without_jedi(tmp_path):
    config, _ = setup(tmp_path)
    analyzer, nodes, _ = analyzer_for(config)
    try:
        owner = ident(nodes, "Box")
        assert analyzer.member(owner, "missing") is None
        assert analyzer.executed_queries == 0
        assert purposes(analyzer, analyzer.module_for[owner]) & 8 == 8
    finally:
        analyzer.close()


def test_resolve_memo_hit_keeps_new_readers_consumer_identity(tmp_path):
    config, _ = setup(tmp_path)
    analyzer, nodes, trees = analyzer_for(config)
    try:
        target, reader = ident(nodes, "target"), ident(nodes, "use")
        expression = trees[target].body[0].value
        old = analyzer.resolve(target, expression)
        root = (reader, id(trees[reader].body[0].value), (1, 0))
        analyzer.stack.append(root)
        try:
            assert analyzer.resolve(target, expression) == old
        finally:
            analyzer.stack.pop()
        assert purposes(analyzer, analyzer.module_for[reader]) & 16 == 16
    finally:
        analyzer.close()


@pytest.mark.parametrize("noise", [0, 20])
def test_purpose_records_survive_local_update_failure_and_full_comparison(tmp_path, monkeypatch, noise):
    import lct.extract as extraction
    config, repo = setup(tmp_path, calls=True, noise=noise)
    first = build(config, offline=True, lexical_only=True)
    assert first["analysis_input_schema"] == 2
    assert first["analysis_input_coverage"] == "captured-analysis-scopes-partial"
    old = records(config, first["version"])
    provider = repo / "src/a.py"
    provider.write_text(provider.read_text().replace("return value", "return None"))
    parsed, actual = [], extraction.python_nodes
    def parse(file):
        parsed.append(file["path"])
        return actual(file)
    monkeypatch.setattr(extraction, "python_nodes", parse)
    with pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == first["version"] and records(config, first["version"]) == old
    parsed.clear()
    updated = build(config, offline=True, lexical_only=True)
    assert parsed == ["src/a.py"]
    fresh_config = dict(config, data=str(tmp_path / "full"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(fresh_config, fresh["version"])
    assert records(config, first["version"]) == old
    parsed.clear()
    same = build(config, offline=True, lexical_only=True)
    assert parsed == [] and records(config, same["version"]) == records(config, updated["version"])


def test_actual_schema1_scope_rows_are_readable_but_not_new_admission(tmp_path):
    config, _ = setup(tmp_path, calls=True)
    built = build(config, offline=True, lexical_only=True)
    assert built["analysis_input_schema"] == 2
    folder, metadata = manifest(config, built["version"])
    repository = config["repositories"][0]["name"]
    with FileDependencies(folder, metadata) as deps:
        expected = deps.input_scope_readers(repository, "src/a.py")
    legacy = tmp_path / "schema1"
    legacy.mkdir()
    shutil.copyfile(folder / GRAPH_SITES, legacy / GRAPH_SITES)
    shutil.copyfile(folder / "catalog.sqlite", legacy / "catalog.sqlite")
    with sqlite3.connect(legacy / GRAPH_SITES) as db:
        db.execute("alter table analysis_input_consumers drop column purposes")
    checksum, size = hash_artifact(legacy, GRAPH_SITES)
    old = dict(metadata, analysis_input_schema=1,
               analysis_input_coverage="captured-query-scopes-partial",
               artifacts={**metadata["artifacts"], GRAPH_SITES: checksum},
               artifact_sizes={**metadata["artifact_sizes"], GRAPH_SITES: size})
    with FileDependencies(legacy, old) as deps:
        assert deps.input_scope_readers(repository, "src/a.py") == expected
        from lct.python_incremental import prepare
        assert prepare(None, old, [], [], dependencies=deps, graph_sites=None) == (
            None, "previous-analysis-input-evidence-unavailable")
