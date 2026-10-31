"""Independent public-build checks; no provider, real source or service access."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

import lct.extract as extraction
import lct.storage as storage
from lct.common import ToolError
from lct.storage import build, current, graph_detail, manifest
from tests.synthetic_support import initialize


def commit(repo):
    for args in (("add", "."), ("-c", "commit.gpgsign=false", "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def contents(c, version):
    folder, meta = manifest(c, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = sorted(row[0] for row in db.execute("select data from nodes"))
        edges = sorted(row[0] for row in db.execute("select data from edges"))
    sites = sorted(json.dumps(s, sort_keys=True) for s in graph_detail(folder, meta)["sites"])
    return nodes, edges, sites


def fixture(tmp_path):
    c, repo = initialize(tmp_path / "code")
    _, docs = initialize(tmp_path / "documentation")
    (docs / "src/weights.py").unlink()
    commit(docs)
    c["repositories"].append(dict(name="separate-docs", path=str(docs), code_roots=["src"]))
    return c, repo, docs


@pytest.mark.parametrize("unrelated", [0, 20])
def test_document_edit_then_failure_keeps_old_graph_and_matches_full(tmp_path, monkeypatch, unrelated):
    c, repo, docs = fixture(tmp_path)
    for i in range(unrelated):
        (repo / "src" / f"noise_{i}.py").write_text(f"def unrelated_{i}(): return {i}\n")
    if unrelated:
        commit(repo)
    before = build(c, offline=True, lexical_only=True)
    saved = contents(c, before["version"])
    (docs / "docs/guide.md").write_text("# Replacement\n\nDifferent headings and content.\n")
    commit(docs)
    parsed = []
    original = extraction.python_nodes

    def counted(file):
        parsed.append((file["repository"], file["path"]))
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    with pytest.raises(ToolError, match="Injected interruption"):
        build(c, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(c) == before["version"]
    assert contents(c, before["version"]) == saved
    assert parsed == [], parsed
    after = build(c, offline=True, lexical_only=True)
    assert parsed == [], parsed
    assert contents(c, before["version"]) == saved
    oracle = dict(c, data=str(tmp_path / "full-oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert len(parsed) == unrelated + 1
    assert contents(c, after["version"]) == contents(oracle, full["version"])


def test_same_python_repository_document_change_requires_new_versions(tmp_path, monkeypatch):
    c, repo, _ = fixture(tmp_path)
    old = build(c, offline=True, lexical_only=True)
    prior = contents(c, old["version"])
    (repo / "docs/guide.md").write_text("# Same repository change\n")
    commit(repo)
    parsed = []
    original = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    new = build(c, offline=True, lexical_only=True)
    assert parsed == ["src/weights.py"]
    oracle = dict(c, data=str(tmp_path / "full-oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert contents(c, new["version"]) == contents(oracle, full["version"])
    assert contents(c, old["version"]) == prior


def test_reuse_keeps_embedding_member_order_after_prior_python_update(tmp_path, monkeypatch):
    c, repo, docs = fixture(tmp_path)
    # A Python-only repository must still retain its repository catalog node.
    (repo / "docs/guide.md").unlink()
    target = repo / "src/weights.py"
    target.write_text("def later(): return 2\n")
    commit(repo)
    build(c, offline=True, lexical_only=True)
    target.write_text("def earlier(): return 1\n\ndef later(): return 2\n")
    commit(repo)
    build(c, offline=True, lexical_only=True)
    (docs / "docs/guide.md").write_text("# Edited documentation\n")
    commit(docs)
    captured = []
    original = storage.embedding_texts

    def record(nodes, files):
        result = original(nodes, files)
        captured.append(result)
        return result

    monkeypatch.setattr(storage, "embedding_texts", record)
    fast = build(c, offline=True, lexical_only=True)
    oracle = dict(c, data=str(tmp_path / "full-oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert captured[0] == captured[1]
    assert contents(c, fast["version"]) == contents(oracle, full["version"])
