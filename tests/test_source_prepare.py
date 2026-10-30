"""Captured Python graph reuse through the public build, with full-build controls."""

import sqlite3
import subprocess

import lct.extract as extraction
import lct.storage as storage
from tests.synthetic_support import initialize


def _records(c, version):
    folder, _ = storage.manifest(c, version)
    result = []
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        for table in ("nodes", "edges"):
            result.append(sorted(raw for (raw,) in db.execute(f"select data from {table}")))
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        for table in ("sites", "query_observations", "import_dependencies", "import_requests"):
            result.append(sorted(raw for (raw,) in db.execute(f"select data from {table}")))
    return result


def test_unchanged_python_only_repository_skips_parse_and_graph_analysis(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "docs" / "guide.md").unlink()
    first = storage.build(c, lexical_only=True)
    original = _records(c, first["version"])
    def no_python_parse(*args):
        raise AssertionError("Python parse on exact capture")
    def no_graph_analysis(*args, **kwargs):
        raise AssertionError("Graph analysis on exact capture")
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "python_nodes", no_python_parse)
        patch.setattr(storage.Graph, "build", no_graph_analysis)
        updated = storage.build(c, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["python_files_parsed"] == 0
    assert updated["incremental"]["analysis_scope"]["python_ast_context_files"] == 0
    assert updated["graph"]["jedi_queries_executed"] == 0
    assert _records(c, updated["version"]) == original
    assert _records(c, first["version"]) == original


def test_python_edit_add_delete_and_corrupt_sidecar_force_full(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    for path, content, expected in (("src/weights.py", "def changed(): pass\n", "full-graph"),
                                    ("src/added.py", "def added(): pass\n", "certified-simple-python-component"),
                                    ("src/added.py", None, "full-graph")):
        target = repo / path
        if content is None:
            target.unlink()
        else:
            target.write_text(content)
        parsed.clear()
        result = storage.build(c, lexical_only=True)
        assert result["incremental"]["analysis_scope"]["mode"] == expected
        assert parsed
    folder, _ = storage.manifest(c, result["version"])
    (folder / "graph-sites.sqlite").write_bytes(b"corrupt")
    parsed.clear()
    result = storage.build(c, lexical_only=True)
    assert result["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert parsed
    assert first["version"] != result["version"]


def test_reused_member_order_matches_fresh_after_prepended_definition(tmp_path, monkeypatch):
    c, repo = initialize(tmp_path / "fixture")
    _, docs = initialize(tmp_path / "documentation")
    (docs / "src" / "weights.py").unlink()
    c["repositories"].append(dict(name="documentation", path=str(docs), code_roots=["src"]))
    storage.build(c, lexical_only=True)
    source = repo / "src" / "weights.py"
    source.write_text("def prepended(): pass\n" + source.read_text())
    storage.build(c, lexical_only=True)  # Fresh extraction appends the earlier declaration.
    (docs / "docs" / "guide.md").write_text("# New documentation\n")
    subprocess.run(["git", "-C", str(docs), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(docs), "-c", "commit.gpgsign=false", "commit",
                    "-m", "documentation"], check=True, capture_output=True)
    observed = []
    original = storage.embedding_texts
    def capture(nodes, files):
        result = original(nodes, files)
        observed.append(result)
        return result
    monkeypatch.setattr(storage, "embedding_texts", capture)
    reused = storage.build(c, lexical_only=True)
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = storage.build(oracle, lexical_only=True)
    assert reused["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert observed[0] == observed[1]
    assert _records(c, reused["version"]) == _records(oracle, full["version"])
