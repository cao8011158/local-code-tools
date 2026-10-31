"""Partial analysis-read sidecar lifecycle and indexed reverse access."""

import shutil
import sqlite3

import pytest

from lct.common import ToolError
from lct.python_incremental import merge_analysis_dependencies
from lct.storage import GRAPH_SITES, FileDependencies, build, current, hash_artifact, manifest
from tests.synthetic_support import initialize


def _base(tmp_path):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run():\n    return registry['go']()\n")
    return config, repo


def test_observed_fallback_read_and_capture_wide_future_writer_watch(tmp_path):
    config, repo = _base(tmp_path)
    (repo / "src/a.py").write_text(
        "def writer(registry):\n    registry['x']=1\n")
    result = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, result["version"])
    assert meta["analysis_dependency_coverage"] == "partial"
    assert not meta["analysis_dependency_truncated"]
    with FileDependencies(folder, meta) as relations:
        assert ("synthetic-review", "src/b.py") in relations.analysis_readers(
            "synthetic-review", "src/a.py")
        assert ("synthetic-review", "src/b.py") in relations.analysis_watchers(
            "slot-writer-universe")
        assert relations.analysis_readers("foreign", "src/a.py") == set()
        for sql, args, index in (
            ("select consumer_repository,consumer_path from analysis_reads where "
             "producer_repository=? and producer_path=? and kind='container-effects'",
             ("synthetic-review", "src/a.py"), "analysis_read_producer"),
            ("select consumer_repository,consumer_path from analysis_watches where "
             "kind=? and universe='all-captured-python'",
             ("slot-writer-universe",), "analysis_watch_kind"),
        ):
            plan = " ".join(row[3] for row in relations.db.execute(
                "explain query plan " + sql, args))
            assert "SEARCH" in plan and index in plan and "SCAN" not in plan, plan
    old = result["version"]
    # A newly added isolated writer cannot become an observed read, yet the
    # prior watch can find B before that new file has any relation at all.
    (repo / "src/a.py").write_text(
        "def writer():\n    slot={}\n    slot['x']=1\n")
    with FileDependencies(folder, meta) as relations:
        assert ("synthetic-review", "src/b.py") in relations.analysis_watchers(
            "slot-writer-universe")
    changed = build(config, offline=True, lexical_only=True)
    new_folder, new_meta = manifest(config, changed["version"])
    with FileDependencies(new_folder, new_meta) as relations:
        assert ("synthetic-review", "src/b.py") not in relations.analysis_readers(
            "synthetic-review", "src/a.py")
        assert ("synthetic-review", "src/b.py") in relations.analysis_watchers(
            "slot-writer-universe")
    assert old != changed["version"]


def test_nested_copy_records_transitive_actual_scope_chain(tmp_path):
    config, repo = _base(tmp_path)
    (repo / "src/b.py").write_text(
        "from a import copied\ndef run():\n    return copied['go']()\n")
    (repo / "src/c.py").write_text("def target(): pass\nsource={'go':target}\n")
    (repo / "src/a.py").write_text("from c import source\ncopied={**source}\n")
    result = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, result["version"])
    with FileDependencies(folder, meta) as relations:
        assert ("synthetic-review", "src/b.py") in relations.analysis_readers(
            "synthetic-review", "src/a.py")
        assert ("synthetic-review", "src/a.py") in relations.analysis_readers(
            "synthetic-review", "src/c.py")
        assert ("synthetic-review", "src/a.py") in relations.analysis_watchers(
            "slot-writer-universe")


def test_identical_reuse_failure_publication_and_legacy_sidecar(tmp_path):
    config, repo = _base(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, first["version"])
    with FileDependencies(folder, meta) as relations:
        before = list(relations.db.execute("select * from analysis_reads"))
        watches = list(relations.db.execute("select * from analysis_watches"))
    identical = build(config, offline=True, lexical_only=True)
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    next_folder, next_meta = manifest(config, identical["version"])
    with FileDependencies(next_folder, next_meta) as relations:
        assert list(relations.db.execute("select * from analysis_reads")) == before
        assert list(relations.db.execute("select * from analysis_watches")) == watches
    pointer = current(config)
    (repo / "src/b.py").write_text((repo / "src/b.py").read_text() + "\ndef extra(): pass\n")
    with pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == pointer
    with FileDependencies(next_folder, next_meta) as relations:
        assert list(relations.db.execute("select * from analysis_watches")) == watches
    staged = tmp_path / "legacy"
    staged.mkdir()
    shutil.copy2(next_folder / GRAPH_SITES, staged / GRAPH_SITES)
    with sqlite3.connect(staged / GRAPH_SITES) as db:
        db.execute("drop table analysis_reads")
    checksum, size = hash_artifact(staged, GRAPH_SITES)
    missing = dict(next_meta, artifacts={**next_meta["artifacts"], GRAPH_SITES: checksum},
                   artifact_sizes={**next_meta["artifact_sizes"], GRAPH_SITES: size})
    with pytest.raises(ToolError, match="unavailable"):
        FileDependencies(staged, missing)
    with pytest.raises(ToolError, match="unavailable"):
        FileDependencies(next_folder, dict(next_meta, dependency_store="indexed-v2"))


def test_record_budget_marks_partial_queries_unavailable(tmp_path, monkeypatch):
    import lct.python_analysis as analysis

    config, repo = _base(tmp_path)
    (repo / "src/a.py").write_text("def writer(registry):\n    registry['x']=1\n")
    monkeypatch.setattr(analysis, "ANALYSIS_DEPENDENCY_LIMIT", 1)
    result = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, result["version"])
    assert meta["analysis_dependency_truncated"]
    assert meta["analysis_read_count"] + meta["analysis_watch_count"] == 1
    with FileDependencies(folder, meta) as relations:
        with pytest.raises(ToolError, match="truncated"):
            relations.analysis_readers("synthetic-review", "src/a.py")
        with pytest.raises(ToolError, match="truncated"):
            relations.analysis_watchers("slot-writer-universe")


def test_local_sidecar_merge_replaces_selected_consumer_and_checks_endpoints(monkeypatch):
    import lct.python_analysis as analysis

    a, b, c = (f"repo:src/{name}.py:module:{name}#1" for name in "abc")
    old_nodes = {ident: dict(repository="repo", path=f"src/{name}.py", kind="module")
                 for ident, name in ((a, "a"), (b, "b"), (c, "c"))}
    new_nodes = dict(old_nodes)
    selected = {("repo", "src/a.py")}
    verified = {("repo", "src/b.py"), ("repo", "src/c.py")}
    old_reads = [(a, b, "container-effects"), (b, c, "container-effects")]
    old_watches = [(a, "slot-writer-universe", "all-captured-python")]
    retained_watch = (b, "slot-writer-universe", "all-captured-python")
    new_reads = [(a, c, "container-effects")]
    new_watches = [(a, "slot-writer-universe", "all-captured-python")]

    def merge(*, old_watches_=old_watches, **overrides):
        args = dict(selected=selected, old_nodes=old_nodes, new_nodes=new_nodes,
                    verified=verified)
        args.update(overrides)
        return merge_analysis_dependencies(old_reads, old_watches_, new_reads, new_watches,
                                           **args)

    merged, reason = merge()
    assert reason is None
    assert merged == (sorted([new_reads[0], old_reads[1]]), sorted(old_watches))
    assert merge(old_watches_=[*old_watches, retained_watch])[1] == (
        "old-analysis-watch-crosses-selected-boundary")
    retained, reason = merge(selected=set(), verified={*verified, ("repo", "src/a.py")},
                             old_watches_=[*old_watches, retained_watch])
    assert reason is None and retained[1] == sorted([*old_watches, retained_watch])
    assert merge(new_nodes={k: v for k, v in new_nodes.items() if k != c})[0] is None
    assert merge(selected={*selected, ("repo", "src/c.py")})[1] == (
        "old-analysis-read-crosses-selected-boundary")
    assert merge(old_truncated=True)[0] is None
    monkeypatch.setattr(analysis, "ANALYSIS_DEPENDENCY_LIMIT", 2)
    assert merge()[1] == "combined-analysis-dependency-budget-uncertified"


def test_real_certified_local_path_keeps_empty_analysis_records(tmp_path):
    config, repo = initialize(tmp_path / "simple")
    (repo / "src/weights.py").write_text("def one(): pass\n")
    (repo / "src/other.py").write_text("def idle(): pass\n")
    (repo / "docs/guide.md").unlink()
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["simple_python_certificate"]
    (repo / "src/weights.py").write_text("def one(): pass\ndef two(): pass\n")
    local = build(config, offline=True, lexical_only=True)
    assert local["incremental"]["analysis_scope"]["mode"] == "full-graph"
    folder, meta = manifest(config, local["version"])
    with FileDependencies(folder, meta) as relations:
        assert relations.analysis_readers("synthetic-review", "src/weights.py") == set()
        assert relations.analysis_watchers("slot-writer-universe") == set()


def test_reverse_query_work_does_not_scan_unrelated_records(tmp_path):
    config, repo = _base(tmp_path)
    observations = []
    for size in (0, 100):
        for number in range(size):
            path = repo / f"src/unrelated_{number}.py"
            if not path.exists():
                path.write_text(f"def f_{number}(): pass\n"
                                f"data={{'x':f_{number}}}\n"
                                "def run():\n    data['x']()\n")
        version = build(config, offline=True, lexical_only=True)["version"]
        folder, meta = manifest(config, version)
        with FileDependencies(folder, meta) as relations:
            sql = ("select consumer_repository,consumer_path from analysis_reads "
                   "where producer_repository=? and producer_path=? and kind='container-effects'")
            args = ("synthetic-review", "src/b.py")
            plan = " ".join(row[3] for row in relations.db.execute(
                "explain query plan " + sql, args))
            assert "analysis_read_producer" in plan and "SCAN" not in plan
            work = [0]
            relations.db.set_progress_handler(lambda: work.__setitem__(0, work[0] + 1), 1)
            try:
                rows = list(relations.db.execute(sql, args))
            finally:
                relations.db.set_progress_handler(None, 0)
            assert rows == [("synthetic-review", "src/b.py")]
            observations.append(work[0])
    assert observations[1] <= observations[0] + 12, observations
