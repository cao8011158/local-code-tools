"""Observed cross-module reads remain partial evidence, but selection consumes them."""

import shutil
import sqlite3

import pytest

from lct.common import ToolError, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.storage import (GRAPH_SITES, FileDependencies, build, hash_artifact,
                         manifest)
from tests.synthetic_support import initialize


def fixture(tmp_path):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    return config, repo


def rows(config, version):
    folder, meta = manifest(config, version)
    with FileDependencies(folder, meta) as deps:
        return set(deps.db.execute(
            "select consumer_path,producer_path,kind from analysis_reads"))


def test_observed_return_member_and_jedi_reads_include_absent_member(tmp_path):
    config, repo = fixture(tmp_path)
    (repo / "src/a.py").write_text(
        "def target(): pass\ndef factory(): return target\n"
        "class Box:\n def go(self): pass\n")
    (repo / "src/b.py").write_text(
        "from a import factory, Box\ndef run():\n factory()()\n"
        " Box().go()\n Box().missing()\n")
    version = build(config, offline=True, lexical_only=True)["version"]
    observed = rows(config, version)
    assert {("src/b.py", "src/a.py", kind) for kind in
            ("return-body", "member-lookup", "jedi-target")} <= observed
    folder, meta = manifest(config, version)
    assert meta["analysis_dependency_schema"] == 2
    assert meta["analysis_dependency_coverage"] == "partial"
    with FileDependencies(folder, meta) as deps:
        assert deps.analysis_readers("synthetic-review", "src/a.py") == {
            ("synthetic-review", "src/b.py")}
        sql = ("select consumer_repository,consumer_path from analysis_reads "
               "where producer_repository=? and producer_path=?")
        plan = " ".join(r[3] for r in deps.db.execute(
            "explain query plan " + sql, ("synthetic-review", "src/a.py")))
        assert "SEARCH analysis_reads USING COVERING INDEX analysis_read_producer" in plan


def test_matched_callback_argument_read_excludes_rejected_candidate(tmp_path):
    config, repo = fixture(tmp_path)
    (repo / "src/a.py").write_text("def invoke(callback): callback()\n")
    (repo / "src/b.py").write_text(
        "from a import invoke\ndef target(): pass\ndef run(): invoke(target)\n")
    (repo / "src/c.py").write_text("def unrelated(callback): callback()\ndef run(): unrelated(1)\n")
    version = build(config, offline=True, lexical_only=True)["version"]
    observed = rows(config, version)
    assert ("src/a.py", "src/b.py", "parameter-origin") in observed
    assert not any(kind == "parameter-origin" and producer == "src/c.py"
                   for consumer, producer, kind in observed if consumer == "src/a.py")


def test_cached_captured_jedi_target_records_current_consumer(tmp_path):
    config, repo = fixture(tmp_path)
    (repo / "src/a.py").write_text("def factory(): pass\n")
    (repo / "src/b.py").write_text("from a import factory\ndef run(): factory()\n")
    files, repos, _ = inventory(config)
    nodes, trees = extract(files)
    graph = Graph(nodes, trees, repos)
    analyzer = Analyzer(graph.nodes, trees, repos, graph.imported)
    try:
        site = next(s for s in analyzer.sites if s["expression"] == "factory" and
                    analyzer.nodes[s["execution_owner"]]["path"] == "src/b.py")
        analyzer.query(site["execution_owner"], site["_expr"])
        read = next(r for r in analyzer.analysis_reads if r[2] == "jedi-target")
        assert analyzer.nodes[read[0]]["path"] == "src/b.py"
        assert analyzer.nodes[read[1]]["path"] == "src/a.py"
        analyzer.analysis_reads.clear()
        executed = analyzer.executed_queries
        analyzer.query(site["execution_owner"], site["_expr"])
        assert analyzer.executed_queries == executed
        assert read in analyzer.analysis_reads
    finally:
        analyzer.close()


def test_old_schema_kind_validation_and_truncation_fail_closed(tmp_path):
    config, repo = fixture(tmp_path)
    (repo / "src/a.py").write_text("def invoke(callback): callback()\n")
    (repo / "src/b.py").write_text(
        "from a import invoke\ndef target(): pass\ndef run(): invoke(target)\n")
    version = build(config, offline=True, lexical_only=True)["version"]
    folder, meta = manifest(config, version)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    shutil.copy2(folder / GRAPH_SITES, legacy / GRAPH_SITES)
    with sqlite3.connect(legacy / GRAPH_SITES) as db:
        db.execute("delete from analysis_reads where kind != 'container-effects'")
        count = db.execute("select count(*) from analysis_reads").fetchone()[0]
    checksum, size = hash_artifact(legacy, GRAPH_SITES)
    old = dict(meta, analysis_dependency_schema=1, analysis_read_count=count,
               artifacts={**meta["artifacts"], GRAPH_SITES: checksum},
               artifact_sizes={**meta["artifact_sizes"], GRAPH_SITES: size})
    with FileDependencies(legacy, old) as deps:
        assert deps.analysis_readers("synthetic-review", "src/b.py") == set()
    with pytest.raises(ToolError, match="records unavailable"):
        FileDependencies(folder, dict(meta, analysis_dependency_schema=1))
    # A separate copy with an actual populated row exercises unknown-kind rejection.
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    shutil.copy2(folder / GRAPH_SITES, unknown / GRAPH_SITES)
    with sqlite3.connect(unknown / GRAPH_SITES) as db:
        db.execute("update analysis_reads set kind='unknown-kind' where rowid=(select min(rowid) from analysis_reads)")
    checksum, size = hash_artifact(unknown, GRAPH_SITES)
    bad = dict(meta, artifacts={**meta["artifacts"], GRAPH_SITES: checksum},
               artifact_sizes={**meta["artifact_sizes"], GRAPH_SITES: size})
    with pytest.raises(ToolError, match="records unavailable"):
        FileDependencies(unknown, bad)
    with pytest.raises(ToolError, match="records unavailable"):
        FileDependencies(folder, dict(meta, analysis_dependency_truncated=True,
                                      analysis_read_count=meta["analysis_read_count"] - 1))
    with FileDependencies(folder, dict(meta, analysis_dependency_truncated=True)) as deps:
        with pytest.raises(ToolError, match="truncated"):
            deps.analysis_readers("synthetic-review", "src/b.py")
