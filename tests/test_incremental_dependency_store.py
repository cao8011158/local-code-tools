"""Public snapshot stores indexed old relations without enabling partial graph analysis."""

import json
import shutil
import sqlite3
import subprocess

import pytest

from lct.common import ToolError
from lct.storage import GRAPH_SITES, FileDependencies, build, hash_artifact, manifest
from tests.synthetic_support import initialize


def commit(repo):
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit",
                    "-m", "synthetic change"], check=True, capture_output=True)


def test_missing_module_request_then_added_module_and_reverse_adjacency(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "caller.py").write_text(
        "from absent import new_handler\nfrom target import old_handler\nold_handler()\n")
    (repo / "src" / "target.py").write_text("def old_handler(): pass\n")
    (repo / "src" / "external_a.py").write_text("import json\n")
    (repo / "src" / "external_b.py").write_text("import json\n")
    commit(repo)
    old = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, old["version"])
    source = ("synthetic-review", "src/caller.py")
    target = ("synthetic-review", "src/target.py")
    with FileDependencies(folder, meta) as relations:
        assert source in relations.importers("synthetic-review", "absent")
        assert source in relations.importers("synthetic-review", "target")
        assert target in relations.adjacent(*source)
        assert source in relations.adjacent(*target)
        assert ("synthetic-review", "src/weights.py") not in relations.adjacent(*source)
        assert ("synthetic-review", "src/external_b.py") not in relations.adjacent(
            "synthetic-review", "src/external_a.py")
    with sqlite3.connect(folder / GRAPH_SITES) as db:
        request = [json.loads(row[0]) for row in db.execute("select data from import_requests")]
        assert any(r["requested_module"] == "absent" and r["status"] != "resolved"
                   for r in request)
    (repo / "src" / "absent.py").write_text("def new_handler(): pass\n")
    commit(repo)
    new = build(c, offline=True, lexical_only=True)
    new_folder, new_meta = manifest(c, new["version"])
    with FileDependencies(folder, meta) as previous:
        assert source in previous.importers("synthetic-review", "absent")
    with FileDependencies(new_folder, new_meta) as current:
        assert source in current.adjacent("synthetic-review", "src/absent.py")


def test_indexed_growth_and_legacy_or_corrupt_evidence_fails_closed(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src" / "caller.py").write_text("from target import old_handler\nold_handler()\n")
    (repo / "src" / "target.py").write_text("def old_handler(): pass\n")
    for i in range(35):
        (repo / "src" / f"unrelated_{i}.py").write_text(f"def unrelated_{i}(): pass\n")
    commit(repo)
    result = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, result["version"])
    with FileDependencies(folder, meta) as relations:
        db = relations.db
        for sql, args, index in [
            ("select source_repository,source_path from import_requests where lookup_repository=? and requested_module=?",
             ("synthetic-review", "target"), "import_request_lookup"),
            ("select target_repository,target_path from file_adjacency where source_repository=? and source_path=?",
             ("synthetic-review", "src/caller.py"), "sqlite_autoindex_file_adjacency_1"),
            ("select source_repository,source_path from file_adjacency where target_repository=? and target_path=?",
             ("synthetic-review", "src/target.py"), "file_adjacency_target"),
        ]:
            plan = " ".join(row[3] for row in db.execute("explain query plan " + sql, args))
            assert "SEARCH" in plan and index in plan and "SCAN" not in plan, plan
        assert len(relations.adjacent("synthetic-review", "src/caller.py")) == 1
    legacy = {k: v for k, v in meta.items() if k != "dependency_store"}
    with pytest.raises(ToolError, match="unavailable"):
        FileDependencies(folder, legacy)
    corrupted = dict(meta, artifacts={**meta["artifacts"], GRAPH_SITES: "0" * 64})
    with pytest.raises(ToolError, match="integrity"):
        FileDependencies(folder, corrupted)
    staged = tmp_path / "legacy-copy"
    staged.mkdir()
    shutil.copy2(folder / GRAPH_SITES, staged / GRAPH_SITES)
    with sqlite3.connect(staged / GRAPH_SITES) as db:
        db.execute("drop table file_adjacency")
    checksum, size = hash_artifact(staged, GRAPH_SITES)
    missing = dict(meta, artifacts={**meta["artifacts"], GRAPH_SITES: checksum},
                   artifact_sizes={**meta["artifact_sizes"], GRAPH_SITES: size})
    with pytest.raises(ToolError, match="unavailable"):
        FileDependencies(staged, missing)


def test_namespace_child_lookup_is_indexed_without_changing_request_evidence(tmp_path):
    c, repo = initialize(tmp_path / "namespace")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/pkg").mkdir()
    (repo / "src/caller.py").write_text(
        "from pkg import foo as chosen\ndef run():\n    return chosen()\n")
    old = build(c, offline=True, lexical_only=True)
    folder, prior = manifest(c, old["version"])
    source = ("synthetic-review", "src/caller.py")
    with FileDependencies(folder, prior) as indexed:
        assert indexed.adjacent(*source) == set()
        assert indexed.importers("synthetic-review", "pkg.foo") == {source}
        assert indexed.requesters("synthetic-review", "pkg.foo") == {source}
        assert indexed.importers("synthetic-review", "pkg.chosen") == set()
        assert indexed.importers("other-repository", "pkg.foo") == set()
        # The same source also requests `pkg` and is already selected if a
        # pkg.py ancestor appears, whereas a direct pkg.foo import is not.
        assert not indexed.has_descendant_requesters("synthetic-review", "pkg")
        for sql, args, name in (
            ("select source_repository,source_path from import_lookup_keys "
             "where lookup_repository=? and module=?",
             ("synthetic-review", "pkg.foo"), "import_lookup_namespace"),
            ("select source_repository,source_path from import_lookup_keys "
             "where source_repository=? and module=?",
             ("synthetic-review", "pkg.foo"), "import_lookup_requester"),
        ):
            plan = " ".join(row[3] for row in indexed.db.execute("explain query plan " + sql, args))
            assert "SEARCH" in plan and name in plan and "SCAN" not in plan, plan
        prefix = ("synthetic-review", "pkg.", "pkg/", "pkg")
        ancestor = list(indexed.db.execute(
            "explain query plan select 1 from import_lookup_keys child "
            "where child.source_repository=? and child.module>=? and child.module<? "
            "and not exists (select 1 from import_lookup_keys base "
            "where base.source_repository=child.source_repository and base.module=? "
            "and base.source_path=child.source_path) limit 1", prefix))
        detail = " ".join(row[3] for row in ancestor)
        assert "import_lookup_requester" in detail and "SCAN" not in detail, detail
    with sqlite3.connect(folder / GRAPH_SITES) as db:
        requests = [json.loads(raw) for (raw,) in db.execute("select data from import_requests")]
        assert [(r["requested_module"], r["requested_name"]) for r in requests] == [
            ("pkg", "foo")]
        assert {row[0] for row in db.execute("select module from import_lookup_keys")} == {
            "pkg", "pkg.foo"}
    (repo / "src/pkg/foo.py").write_text("def foo():\n    return 1\n")
    updated = build(c, offline=True, lexical_only=True)
    new_folder, _ = manifest(c, updated["version"])
    def caller_site(folder):
        with sqlite3.connect(folder / GRAPH_SITES) as db:
            return [json.loads(raw) for (raw,) in db.execute("select data from sites")
                    if "src/caller.py" in raw]
    assert caller_site(folder)[0]["unknown_origin"]
    assert caller_site(new_folder)[0]["evidence"][1]["raw"][0]["full_name"] == "pkg.foo"


def test_direct_child_request_still_detects_ancestor_layout(tmp_path):
    c, repo = initialize(tmp_path / "ancestor")
    (repo / "src/caller.py").write_text("from pkg.child import value\n")
    old = build(c, offline=True, lexical_only=True)
    folder, prior = manifest(c, old["version"])
    with FileDependencies(folder, prior) as indexed:
        assert indexed.has_descendant_requesters("synthetic-review", "pkg")
        assert indexed.requesters("synthetic-review", "pkg") == set()


def test_lookup_key_schema_missing_fails_closed(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    old = build(c, offline=True, lexical_only=True)
    folder, prior = manifest(c, old["version"])
    staged = tmp_path / "missing-lookup"
    staged.mkdir()
    shutil.copy2(folder / GRAPH_SITES, staged / GRAPH_SITES)
    with sqlite3.connect(staged / GRAPH_SITES) as db:
        db.execute("drop index import_lookup_requester")
    checksum, size = hash_artifact(staged, GRAPH_SITES)
    missing = dict(prior, artifacts={**prior["artifacts"], GRAPH_SITES: checksum},
                   artifact_sizes={**prior["artifact_sizes"], GRAPH_SITES: size})
    with pytest.raises(ToolError, match="indexes unavailable"):
        FileDependencies(staged, missing)
    with pytest.raises(ToolError, match="unavailable"):
        FileDependencies(folder, dict(prior, dependency_store="indexed-v1"))
