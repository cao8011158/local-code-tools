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
