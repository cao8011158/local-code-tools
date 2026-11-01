"""Unsupported captured Python states preserve the complete analysis path."""

from lct.common import inventory
from lct.unit_incremental import prepare
from lct.storage import GRAPH_SITES, FileDependencies, build, manifest
from tests.test_general_passive_incremental import semantic
from tests.synthetic_support import initialize
from tests.semantic_comparison import assert_semantic_equal
from tests.test_batch3_actual_acceptance import semantic as full_semantic


def fixture(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").write_text("def one(): pass\ndef two(): pass\n")
    (repo / "src/other.py").write_text("def unrelated(): pass\n")
    build(c, offline=True, lexical_only=True)
    return c, repo


def test_class_change_recomputes_complex_module_and_reuses_passive_peer(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "src/weights.py").write_text("class Box(Base):\n    def __init__(self): pass\n")
    result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["python_files_parsed"] == 1
    assert scope["reused_owner_count"] >= 1
    fresh_config = dict(c, data=str(tmp_path / "fresh"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(c, result["version"]),
                          full_semantic(fresh_config, fresh["version"]))


def test_ordinary_class_change_uses_bounded_component(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "src/weights.py").write_text(
        '"""A module."""\nclass Box:\n    """A value."""\n'
        '    def __init__(self):\n        self.cb = one\n'
        '    def call(self):\n        self.cb()\n'
        'def one(): pass\n')
    result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["python_files_parsed"] == 1


def test_simultaneous_document_and_python_change_falls_back(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "src/weights.py").write_text("def one(): return 1\n")
    (repo / "docs/guide.md").write_text("# Changed\n")
    result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["reason"] == "incremental-owners"
    assert scope["python_files_parsed"] == 1


def test_association_bound_survives_local_and_exact_capture_generations(tmp_path):
    c, repo = fixture(tmp_path)
    baseline = build(c, offline=True, lexical_only=True)
    first_bound = baseline["graph"]["association_bound"]
    source = repo / "src/weights.py"
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): one()\n")
    local = build(c, offline=True, lexical_only=True)
    assert local["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert local["graph"]["association_bound"] >= local["graph"]["association_evaluations"]
    identical = build(c, offline=True, lexical_only=True)
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert identical["graph"]["association_evaluations"] == 0
    assert identical["graph"]["association_bound"] == local["graph"]["association_bound"]
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): two()\n")
    second = build(c, offline=True, lexical_only=True)
    assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert second["graph"]["association_bound"] == max(
        identical["graph"]["association_bound"], second["graph"]["association_evaluations"])
    source.write_text("def one(): pass\ndef two(): pass\ndef run(): one()\n")
    old_folder, old_manifest = manifest(c, second["version"])
    files, repos, _ = inventory(c)
    near_budget = dict(old_manifest, graph=dict(old_manifest["graph"], association_bound=20000))
    with FileDependencies(old_folder, old_manifest) as relations:
        candidate, reason = prepare(old_folder, near_budget, files, repos,
                                    dependencies=relations, graph_sites=GRAPH_SITES)
    assert candidate is not None and reason == "incremental-owners", reason
