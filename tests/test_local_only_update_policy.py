"""Public warm-build controls for local scheduling and persisted restart state."""

import json
import subprocess
import sys
from unittest.mock import patch

from lct.graph import Graph
from lct.storage import build, current
from tests.semantic_comparison import assert_semantic_equal
from tests.synthetic_support import forbid_provider, initialize
from tests.test_batch3_actual_acceptance import semantic


def no_full(c):
    original = Graph.build
    def selected_only(graph, *args, **kwargs):
        assert kwargs.get("selected_owners") is not None
        return original(graph, *args, **kwargs)
    with forbid_provider(), patch.object(Graph, "build", selected_only):
        return build(c, offline=True, lexical_only=True)


def fixture(tmp_path):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    c["embedding"].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    (repo / "src/provider.py").write_text(
        "def first(): pass\ndef second(): pass\nclass Box:\n"
        "    def __init__(self): self.cb=first\n")
    (repo / "src/consumer.py").write_text(
        "from provider import Box\ndef run(): Box().cb()\n")
    (repo / "src/idle.py").write_text("def unrelated(): return 1\n")
    with forbid_provider():
        build(c, offline=True, lexical_only=True)
    return c, repo


def fresh_equal(c, result, tmp_path, name):
    fresh_c = dict(c, data=str(tmp_path / name))
    with forbid_provider():
        fresh = build(fresh_c, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(c, result["version"]),
                          semantic(fresh_c, fresh["version"]))


def test_document_then_class_header_change_reuses_unrelated_owner(tmp_path):
    c, repo = fixture(tmp_path)
    (repo / "docs/guide.md").write_text("# Updated guide\n")
    document = no_full(c)
    assert document["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert document["incremental"]["analysis_scope"]["selected_owner_count"] == 0
    fresh_equal(c, document, tmp_path, "fresh-doc")
    source = repo / "src/provider.py"
    source.write_text(source.read_text().replace("class Box:", "class Box(object):"))
    changed = no_full(c)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert not any(":function:unrelated#" in owner for owner in
                   changed["incremental"]["analysis_scope"]["selected_owner_ids"])
    fresh_equal(c, changed, tmp_path, "fresh-header")


def test_restart_uses_persisted_owner_evidence_for_second_update(tmp_path):
    c, repo = fixture(tmp_path)
    source = repo / "src/provider.py"
    source.write_text(source.read_text().replace("self.cb=first", "self.cb=second"))
    first = no_full(c)
    fresh_equal(c, first, tmp_path, "fresh-first")
    source.write_text(source.read_text().replace("self.cb=second", "self.cb=first"))
    script = (
        "import json,sys; from lct.storage import build; "
        "c=json.load(sys.stdin); print(json.dumps(build(c,offline=True,lexical_only=True)))"
    )
    child = subprocess.run([sys.executable, "-c", script], input=json.dumps(c),
                           text=True, capture_output=True, check=True)
    second = json.loads(child.stdout)
    assert current(c) == second["version"]
    assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert second["incremental"]["analysis_scope"]["reused_owner_count"] >= 1
    fresh_equal(c, second, tmp_path, "fresh-restored")
