"""Synthetic captured tree fixtures; hashes do not claim a remote Git origin."""

import copy
import hashlib
from pathlib import Path

import pytest

from lct.common import EXCLUDED, ToolError, atomic, config, digest, inventory
from lct.query import Query
from lct.storage import build


def entry(path, raw):
    blob = b"blob " + str(len(raw)).encode() + b"\0" + raw
    return dict(path=path, git_blob_sha=hashlib.sha1(blob).hexdigest(), sha256=digest(raw), bytes=len(raw))


@pytest.fixture
def captured(tmp_path):
    root = tmp_path / "captured"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    sources = {"src/sample.py": b'"""Sample."""\ndef helper():\n """Weight helper."""\n return 2\n',
               "docs/guide.md": b"# Weight guide\n"}
    for name, raw in sources.items():
        (root / name).write_bytes(raw)
    c = copy.deepcopy(config())
    c["repositories"] = [dict(name="sample", path=str(root), code_roots=["src"],
                              exclude_files=[], source_manifest="source-manifest.json")]
    c["data"] = str(tmp_path / "index")
    c["embedding"]["historical_cache"] = "none"
    scope = dict(code_roots=["src"], include_tests=False, exclude_files=[], docs=True,
                 root_files=[".py", ".md"], excluded_directories=sorted(EXCLUDED))
    manifest = dict(schema=1, repository="sample", head="a" * 40, tree="b" * 40,
                    branch="main", provenance="github-pinned-tree", selected_scope=scope,
                    files=[entry(k, v) for k, v in sources.items()])
    atomic(root / "source-manifest.json", manifest)
    return c, root, manifest


def test_captured_build_query_and_no_git(captured, monkeypatch):
    c, root, _ = captured
    monkeypatch.setattr("lct.common.git", lambda *args: (_ for _ in ()).throw(AssertionError("Git called")))
    files, repos, fingerprint = inventory(c)
    assert [f["path"] for f in files] == ["docs/guide.md", "src/sample.py"]
    assert repos[0]["head"] == "a" * 40 and repos[0]["source_manifest_sha256"]
    assert "not Git working tree" in repos[0]["status"] and fingerprint
    build(c, lexical_only=True)
    q = Query(c)
    results = q.search_code("helper", mode="bm25")["results"]
    assert results
    node = q.get_nodes([results[0]["node_id"]])["nodes"][0]
    assert node["path"] == "src/sample.py" and node["live_file_matches"]
    assert q.get_relations([node["node_id"]], direction="in")["edges"]
    assert q.index_status(refresh=True)["freshness"]["status"] == "matched_at_check"
    assert not (root / ".git").exists()


def test_byte_mutation_missing_and_new_included(captured):
    c, root, _ = captured
    source = root / "src/sample.py"
    source.write_bytes(source.read_bytes() + b"# changed\n")
    with pytest.raises(ToolError, match="bytes changed"):
        inventory(c)
    source.unlink()
    with pytest.raises(ToolError, match="missing"):
        inventory(c)
    source.write_bytes(b'"""Sample."""\ndef helper():\n """Weight helper."""\n return 2\n')
    (root / "src/new.py").write_text("def added(): pass\n")
    with pytest.raises(ToolError, match="undeclared"):
        inventory(c)
    (root / "README.txt").write_text("unrelated")


@pytest.mark.parametrize("change,match", [
    (lambda c, m: m.update(repository="other"), "repository mismatch"),
    (lambda c, m: m["files"].append(dict(m["files"][0])), "Duplicate"),
    (lambda c, m: m["files"][0].update(path="../outside.py"), "path"),
    (lambda c, m: m["files"][0].update(path="/outside.py"), "path"),
    (lambda c, m: m["files"][0].update(path="src\\bad.py"), "path"),
    (lambda c, m: c["repositories"][0].update(code_roots=["different"]), "scope"),
])
def test_manifest_rejections(captured, change, match):
    c, root, m = captured
    change(c, m)
    atomic(root / "source-manifest.json", m)
    with pytest.raises(ToolError, match=match):
        inventory(c)


def test_declared_symlink_and_out_of_scope(captured, tmp_path):
    c, root, m = captured
    p = root / "src/sample.py"
    destination = tmp_path / "source.py"
    p.rename(destination)
    p.symlink_to(destination)
    with pytest.raises(ToolError, match="symlink"):
        inventory(c)
    p.unlink()
    p.write_bytes(destination.read_bytes())
    m["files"].append(entry("outside.py", b"def other(): pass\n"))
    (root / "outside.py").write_bytes(b"def other(): pass\n")
    atomic(root / "source-manifest.json", m)
    # Root Python files are eligible, so this is valid; excluded directory is not.
    assert len(inventory(c)[0]) == 3
    (root / "outside.py").unlink()
    (root / "vendor").mkdir()
    (root / "vendor/outside.py").write_bytes(b"def other(): pass\n")
    m["files"][-1]["path"] = "vendor/outside.py"
    atomic(root / "source-manifest.json", m)
    with pytest.raises(ToolError, match="out_of_scope"):
        inventory(c)
