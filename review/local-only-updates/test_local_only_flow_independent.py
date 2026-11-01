"""Root acceptance: warm updates must never enter the cold/full builder."""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from lct.common import ToolError
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.storage import build, current, manifest
from tests.semantic_comparison import assert_semantic_equal
from tests.synthetic_support import forbid_provider, initialize
from tests.test_batch3_actual_acceptance import semantic


def setup_sources(tmp_path, sources):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    c["retained_versions"] = 8
    for name, source in sources.items():
        path = repo / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    with forbid_provider():
        build(c, offline=True, lexical_only=True)
    return c, repo


def local_update(c):
    original = Graph.build
    def disallow_full(graph, *args, **kwargs):
        assert kwargs.get("selected_owners") is not None, "automatic full analysis attempted"
        return original(graph, *args, **kwargs)
    with forbid_provider(), patch.object(Graph, "build", disallow_full):
        result = build(c, offline=True, lexical_only=True)
    assert result["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    return result


def compare_fresh(c, result, tmp_path, label):
    other = dict(c, data=str(tmp_path / label))
    with forbid_provider():
        fresh = build(other, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(c, result["version"]), semantic(other, fresh["version"]))


def call_targets(c, result, owner, expression):
    folder, _ = manifest(c, result["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        names = {n["node_id"]: n["qualname"] for raw, in db.execute("select data from nodes")
                 for n in [json.loads(raw)]}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for raw, in db.execute("select data from sites")]
    site = next(s for s in sites if names[s["execution_owner"]] == owner
                and s["expression"] == expression)
    return {names.get(t, t) for t in site["targets"]}


def test_unknown_receiver_does_not_disable_real_callback_updates(tmp_path):
    source = ("from worker import execute\ndef first(): pass\ndef second(): pass\n"
              "def run(): execute(first)\n")
    c, repo = setup_sources(tmp_path, {"caller.py": source,
        "worker.py": "def execute(callback): callback()\nclass Opaque:\n    def ignored(self): self.client.work()\n",
        "idle.py": "def unrelated(): return 1\n"})
    for source_name, target_name in (("first", "second"), ("second", "first")):
        path = repo / "src/caller.py"
        path.write_text(path.read_text().replace(f"execute({source_name})", f"execute({target_name})"))
        updated = local_update(c)
        assert call_targets(c, updated, "execute", "callback") == {target_name}
        compare_fresh(c, updated, tmp_path, "fresh-" + target_name)


@pytest.mark.parametrize("change", ["add_file", "add_definition", "delete_definition", "delete_file"])
def test_namespace_membership_changes_update_real_import_consumers(tmp_path, change):
    initial = "def target(): return 1\n" if change.startswith("delete") else "def unrelated(): pass\n"
    sources = {"consumer.py": "from provider import target\ndef run(): target()\n",
               "idle.py": "def idle(): return 1\n"}
    if change != "add_file":
        sources["provider.py"] = initial
    c, repo = setup_sources(tmp_path, sources)
    path = repo / "src/provider.py"
    if change in {"add_file", "add_definition"}:
        path.write_text(initial + "\ndef target(): return 2\n")
    elif change == "delete_definition":
        path.write_text("def unrelated(): pass\n")
    else:
        path.unlink()
    updated = local_update(c)
    targets = call_targets(c, updated, "run", "target")
    assert ("target" in targets) is change.startswith("add")
    compare_fresh(c, updated, tmp_path, "fresh-membership")


def test_package_reexport_change_retargets_existing_consumer(tmp_path):
    c, repo = setup_sources(tmp_path, {
        "pkg/__init__.py": "from .provider import first as chosen\n",
        "pkg/provider.py": "def first(): pass\ndef second(): pass\n",
        "consumer.py": "from pkg import chosen\ndef run(): chosen()\n",
        "idle.py": "def idle(): return 1\n"})
    (repo / "src/pkg/__init__.py").write_text("from .provider import second as chosen\n")
    updated = local_update(c)
    assert call_targets(c, updated, "run", "chosen") == {"second"}
    compare_fresh(c, updated, tmp_path, "fresh-reexport")


def test_writer_getter_return_and_terminal_call_update_twice(tmp_path):
    c, repo = setup_sources(tmp_path, {
        "provider.py": "def first(): pass\ndef second(): pass\nhandlers={'go':first}\n",
        "writer.py": "import provider\ndef configure(): provider.handlers['go']=provider.first\n",
        "getter.py": "from provider import handlers\ndef get_callback(): return handlers['go']\n",
        "consumer.py": "from getter import get_callback\ndef run():\n    fn=get_callback()\n    fn()\n",
        "idle.py": "def idle(): return 1\n"})
    path = repo / "src/writer.py"
    for name in ("second", "first"):
        path.write_text(f"import provider\ndef configure(): provider.handlers['go']=provider.{name}\n")
        updated = local_update(c)
        assert name in call_targets(c, updated, "run", "fn")
        compare_fresh(c, updated, tmp_path, "fresh-writer-" + name)


def test_corrupt_snapshot_fails_explicitly_without_replacing_current(tmp_path):
    c, repo = setup_sources(tmp_path, {"one.py": "def run(): return 1\n"})
    previous = current(c)
    folder, _ = manifest(c, previous)
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        db.execute("update unit_ast_cache set payload=?", (b"corrupt",))
    (repo / "src/one.py").write_text("def run(): return 2\n")
    with pytest.raises(ToolError):
        local_update(c)
    assert current(c) == previous


@pytest.mark.parametrize("field", ["program_hash", "config_hash", "query_runtime"])
def test_incompatible_snapshot_cannot_be_reused_by_new_warm_route(tmp_path, field):
    c, repo = setup_sources(tmp_path, {"one.py": "def run(): return 1\n"})
    previous = current(c)
    folder, metadata = manifest(c, previous)
    if field == "query_runtime":
        metadata["graph"][field] = "incompatible-runtime"
    else:
        metadata[field] = "incompatible-version"
    (folder / "summary.json").write_text(json.dumps(metadata))
    (repo / "src/one.py").write_text("def run(): return 2\n")
    with pytest.raises(ToolError):
        local_update(c)
    assert current(c) == previous


@pytest.mark.parametrize("noise", [0, 30])
def test_unknown_writer_selects_subscriber_without_sibling_functions(tmp_path, noise):
    unrelated = "".join(f"def unrelated_{i}(x): return x+{i}\n" for i in range(noise))
    writer = ("import provider\ndef mutate(table): table['go']=provider.first\n"
              "def configure(): mutate(provider.handlers)\n")
    c, repo = setup_sources(tmp_path, {
        "provider.py": "def first(): pass\ndef second(): pass\nhandlers={'go':first}\n",
        "writer.py": writer,
        "consumer.py": "from provider import handlers\ndef run(): handlers['go']()\n" + unrelated})
    (repo / "src/writer.py").write_text(writer.replace("provider.first", "provider.second"))
    original = Analyzer.query
    queried = []
    def observe(analyzer, scope, expr, **kwargs):
        queried.append(analyzer.nodes[scope]["qualname"])
        return original(analyzer, scope, expr, **kwargs)
    with patch.object(Analyzer, "query", observe):
        updated = local_update(c)
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert not any("unrelated_" in name for name in selected)
    assert not any(name.startswith("unrelated_") for name in queried)
    assert "second" in call_targets(c, updated, "run", "handlers['go']")
    compare_fresh(c, updated, tmp_path, "fresh-subscriber")


def test_added_name_in_known_module_does_not_select_unrelated_callers(tmp_path):
    c, repo = setup_sources(tmp_path, {
        "provider.py": "def existing(): return 1\n",
        "consumer.py": "import provider\ndef run(): provider.later()\n",
        "opaque.py": "class Opaque:\n    def ignored(self): self.client.work()\n",
        "idle.py": "def leaf(x: int) -> int: return x+1\ndef unrelated(x: int) -> int: return leaf(x)\n"})
    (repo / "src/provider.py").write_text("def existing(): return 1\ndef later(): return 2\n")
    updated = local_update(c)
    assert call_targets(c, updated, "run", "provider.later") == {"later"}
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert not any(":function:unrelated#" in name or ":function:leaf#" in name for name in selected)
    compare_fresh(c, updated, tmp_path, "fresh-added-name")


def test_limited_initial_analysis_does_not_lose_container_return_consumers(tmp_path):
    sources = {
        "provider.py": "def first(): pass\ndef second(): pass\nhandlers={'go':first}\n",
        "writer.py": "import provider\ndef configure(): provider.handlers['go']=provider.first\n",
        "getter.py": "from provider import handlers\ndef get_callback(): return handlers['go']\n",
        "consumer.py": "from getter import get_callback\ndef run():\n    fn=get_callback()\n    fn()\n"}
    original = Analyzer.__init__
    def limited(analyzer, *args, **kwargs):
        original(analyzer, *args, **kwargs)
        analyzer.budget = 0
    with patch.object(Analyzer, "__init__", limited):
        c, repo = setup_sources(tmp_path, sources)
    previous = current(c)
    _, metadata = manifest(c, previous)
    assert metadata["graph"]["analysis_limited"]
    (repo / "src/writer.py").write_text(sources["writer.py"].replace("provider.first", "provider.second"))
    updated = local_update(c)
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert any(":function:run#" in name for name in selected)
    assert "second" in call_targets(c, updated, "run", "fn")


@pytest.mark.parametrize("parameterized", [False, True])
def test_limited_container_origin_separate_from_callback_definition(tmp_path, parameterized):
    writer = ("import provider, store\ndef mutate(table): table['go']=provider.first\n"
              "def configure(): mutate(store.handlers)\n" if parameterized else
              "import provider, store\ndef configure(): store.handlers['go']=provider.first\n")
    sources = {
        "provider.py": "def first(): pass\ndef second(): pass\n",
        "store.py": "from provider import first\nhandlers={'go':first}\n",
        "writer.py": writer,
        "getter.py": "from store import handlers\ndef get_callback(): return handlers['go']\n",
        "consumer.py": "from getter import get_callback\ndef run():\n    fn=get_callback()\n    fn()\n",
        "idle.py": "def unrelated(): return 1\n"}
    original = Analyzer.__init__
    def limited(analyzer, *args, **kwargs):
        original(analyzer, *args, **kwargs)
        analyzer.budget = 0
    with patch.object(Analyzer, "__init__", limited):
        c, repo = setup_sources(tmp_path, sources)
    (repo / "src/writer.py").write_text(writer.replace("provider.first", "provider.second"))
    updated = local_update(c)
    assert "second" in call_targets(c, updated, "run", "fn")
    assert not any(":function:unrelated#" in name
                   for name in updated["incremental"]["analysis_scope"]["selected_owner_ids"])


@pytest.mark.parametrize("deferred", [False, True])
def test_callee_body_change_does_not_reanalyze_unrelated_importing_file_function(tmp_path, deferred):
    source = (
        "def run():\n    from provider import work\n    work()\n"
        "def unrelated():\n    from other import leaf\n    leaf()\n" if deferred else
        "from provider import work\nfrom other import leaf\n"
        "def run(): work()\ndef unrelated(): leaf()\n")
    c, repo = setup_sources(tmp_path, {
        "provider.py": "def work(): return 1\n",
        "other.py": "def leaf(): return 1\n", "consumer.py": source})
    (repo / "src/provider.py").write_text("def work(): return 2\n")
    original = Analyzer.query
    queried = []
    def observe(analyzer, scope, expr, **kwargs):
        queried.append(analyzer.nodes[scope]["qualname"])
        return original(analyzer, scope, expr, **kwargs)
    with patch.object(Analyzer, "query", observe):
        updated = local_update(c)
    selected = updated["incremental"]["analysis_scope"]["selected_owner_ids"]
    assert not any(":function:unrelated#" in name for name in selected)
    assert "unrelated" not in queried
    assert call_targets(c, updated, "run", "work") == {"work"}
    compare_fresh(c, updated, tmp_path, "fresh-callee")
