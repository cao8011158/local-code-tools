"""Unsupported captured Python states preserve the complete analysis path."""

from lct.common import inventory
from lct.python_incremental import prepare
from lct.storage import GRAPH_SITES, FileDependencies, build, manifest
from tests.synthetic_support import initialize


def fixture(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").write_text("def one(): pass\ndef two(): pass\n")
    (repo / "src/other.py").write_text("def unrelated(): pass\n")
    build(c, offline=True, lexical_only=True)
    return c, repo


def test_class_change_falls_back_after_bounded_preflight(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "src/weights.py").write_text("class Box:\n    def __init__(self): pass\n")
    result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph"
    assert scope["reason"] == "selected-python-syntax-unsupported"
    assert scope["local_preflight_python_files_parsed"] == 1
    assert scope["total_python_files_parsed"] == 3


def test_simultaneous_document_and_python_change_falls_back(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "src/weights.py").write_text("def one(): return 1\n")
    (repo / "docs/guide.md").write_text("# Changed\n")
    result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph"
    assert scope["reason"] == "document-or-other-input-changed"
    assert scope["local_preflight_python_files_parsed"] == 0


def test_association_bound_survives_local_and_exact_capture_generations(tmp_path):
    c, repo = fixture(tmp_path)
    baseline = build(c, offline=True, lexical_only=True)
    first_bound = baseline["graph"]["association_bound"]
    source = repo / "src/weights.py"
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): one()\n")
    local = build(c, offline=True, lexical_only=True)
    assert local["incremental"]["analysis_scope"]["mode"] == "certified-simple-python-component"
    assert local["graph"]["association_bound"] == first_bound + local["graph"]["association_evaluations"]
    identical = build(c, offline=True, lexical_only=True)
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert identical["graph"]["association_evaluations"] == 0
    assert identical["graph"]["association_bound"] == local["graph"]["association_bound"]
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): two()\n")
    second = build(c, offline=True, lexical_only=True)
    assert second["incremental"]["analysis_scope"]["mode"] == "certified-simple-python-component"
    assert second["graph"]["association_bound"] == (
        identical["graph"]["association_bound"] + second["graph"]["association_evaluations"])
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): one()\n")
    old_folder, old_manifest = manifest(c, second["version"])
    files, repos, _ = inventory(c)
    near_budget = dict(old_manifest, graph=dict(old_manifest["graph"], association_bound=20000))
    with FileDependencies(old_folder, old_manifest) as relations:
        candidate, reason = prepare(old_folder, near_budget, files, repos,
                                    dependencies=relations, graph_sites=GRAPH_SITES)
    assert candidate is None and reason == "combined-association-budget-uncertified"
