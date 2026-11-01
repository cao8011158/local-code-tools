"""Full-oracle admission on the exact three-file captured business subset."""
import ast
import shutil
from pathlib import Path

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.simple_python import CERTIFICATE, certify, component_policy
from lct.storage import build
from tests.synthetic_support import initialize
from tests.test_actual_item_unit_incremental import records
from tests.test_batch3_actual_acceptance import semantic
from tests.semantic_comparison import assert_semantic_equal

SOURCE = (Path(__file__).parents[1] / "review/batch4-incremental/fixtures"
          / "actual-source-subset/src/trpg_state_machine")


def setup(tmp_path, noise=0):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    for source in SOURCE.glob("*.py"):
        shutil.copyfile(source, target / source.name)
    for i in range(noise):
        (repo / f"src/unrelated_{i}.py").write_text(f"def unrelated_{i}():\n    return {i}\n")
    return config, repo, target


def oracle(tmp_path, config, updated):
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, updated["version"]),
                          semantic(fresh_config, fresh["version"]))


@pytest.mark.parametrize("noise", [0, 20])
def test_actual_three_file_availability_local_and_full_oracle(tmp_path, noise):
    config, repo, target = setup(tmp_path, noise)
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["simple_python_certificate"] == CERTIFICATE
    old = records(config, baseline["version"])
    module = target / "availability.py"
    module.write_bytes(module.read_bytes().replace(b"context=context", b"context=None"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)
    assert records(config, baseline["version"]) == old


def test_connected_caller_is_selected_and_matches_full(tmp_path):
    config, repo, target = setup(tmp_path)
    (repo / "src/caller.py").write_text(
        "from trpg_state_machine.availability import AvailabilityRuntime\n"
        "def use(value):\n    return AvailabilityRuntime().query_action_availability("
        "value, value, value, value, context=value)\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    module = target / "availability.py"
    module.write_bytes(module.read_bytes().replace(b"context=context", b"context=None"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)


def test_errors_passive_default_and_property_with_importer(tmp_path):
    config, repo, target = setup(tmp_path)
    (repo / "src/consumer.py").write_text(
        "from trpg_state_machine.errors import Issue, StateMachineError\n"
        "def use(message):\n    issue = Issue('x', '', message)\n"
        "    return StateMachineError(issue.code, message).code\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    module = target / "errors.py"
    module.write_bytes(module.read_bytes().replace(b'path: str = ""', b'path: str = "root"'))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)


@pytest.mark.parametrize("noise", [0, 200])
def test_component_candidates_read_only_indexed_sites(tmp_path, noise):
    sources = {"a.py": "def target(): pass\ndef call(): target()\n",
               "b.py": "from a import target\ndef invoke(): target()\n"}
    sources.update({f"noise_{i}.py": f"def irrelevant(): pass\ndef call(): irrelevant()\n"
                    for i in range(noise)})
    nodes, trees, files = [], {}, []
    for path, source in sources.items():
        ns, ts = python_nodes(dict(repository="fixture", path=path, text=source,
                                   sha256=digest(source), is_test=False))
        nodes.extend(ns)
        trees.update(ts)
        files.append(dict(repository="fixture", path=path))
    graph = Graph(nodes, trees, [dict(name="fixture", path=str(tmp_path),
                                      head="captured", closed_world=False)])
    components = component_policy(files, trees, graph)
    a_module, b_module = (f"fixture:{p}:module:{p[:-3]}#1" for p in ("a.py", "b.py"))
    assert components[a_module] is components[b_module]
    assert len({id(x) for x in components.values()}) == noise + 1
    analyzer = Analyzer(graph.nodes, trees, graph.repos, graph.imported,
                        candidate_components=components)
    try:
        target = next(n["node_id"] for n in nodes if n.get("qualname") == "target")
        expected = list(analyzer.candidate_sites(target))
        assert len(expected) == 2

        class GuardList(list):
            def __iter__(self):
                raise AssertionError("global sites iteration")

        analyzer.sites = GuardList(analyzer.sites)
        assert list(analyzer.candidate_sites(target)) == expected
        assert list(analyzer.sites_for(target)) == expected
        analyzer._query_inflight = 1
        assert list(analyzer.candidate_sites(target)) == expected
        analyzer._query_inflight = 0
        analyzer.sites.append(dict(_call=None))
        assert list(analyzer.candidate_sites(target)) == expected
    finally:
        analyzer.close()


def test_missing_catalog_module_ast_disables_component_policy(tmp_path, monkeypatch):
    source = "def f(): pass\n"
    nodes, trees = python_nodes(dict(repository="fixture", path="a.py", text=source,
                                     sha256=digest(source), is_test=False))
    missing, _ = python_nodes(dict(repository="fixture", path="b.py", text=source,
                                   sha256=digest(source), is_test=False))
    graph = Graph(nodes + missing, trees, [dict(name="fixture", path=str(tmp_path),
                                                head="captured", closed_world=False)])
    from lct import graph as graph_module
    observed = []
    original = graph_module.Analyzer

    def record(*args, **kwargs):
        observed.append(kwargs.get("candidate_components"))
        return original(*args, **kwargs)

    monkeypatch.setattr(graph_module, "Analyzer", record)
    graph.build()
    assert observed == [None]


@pytest.mark.parametrize("source", [
    "def __getattr__(name): pass\n",
    "def __getattribute__(name): pass\n",
    "class __getattr__:\n    pass\n",
])
def test_module_magic_definitions_reject_common(source, tmp_path):
    ns, trees = python_nodes(dict(repository="fixture", path="a.py", text=source,
                                  sha256=digest(source), is_test=False))
    graph = Graph(ns, trees, [dict(name="fixture", path=str(tmp_path), head="captured")])
    assert certify([dict(repository="fixture", path="a.py")], trees, graph=graph) is None


@pytest.mark.parametrize("source,node", [
    ("def f(): pass\n", "function"),
    ("class C: pass\n", "class"),
    ("class C:\n    def method(self): pass\n", "method"),
])
def test_generic_type_params_reject_strict_and_common(source, node, tmp_path):
    tree = ast.parse(source)
    selected = (tree.body[0].body[0] if node == "method" else tree.body[0])
    selected.type_params = [ast.Name(id="T", ctx=ast.Load())]
    module_id = "fixture:a.py:module:a#1"
    graph = Graph([dict(node_id=module_id, kind="module", repository="fixture",
                        path="a.py", qualname="a")], {module_id: tree},
                  [dict(name="fixture", path=str(tmp_path), head="captured")])
    assert certify([dict(repository="fixture", path="a.py")], {module_id: tree},
                   graph=graph) is None


@pytest.mark.parametrize("filename,old,new", [
    ("errors.py", "code: str", "code: dangerous()"),
    ("errors.py", "code: str", "code: External"),
    ("errors.py", "@dataclass(frozen=True, slots=True)",
     "@dataclass(frozen=True, slots=True, init=False)"),
    ("errors.py", "class StateMachineError(Exception):", "class StateMachineError(CustomBase):"),
    ("errors.py", "@property", "@other_property"),
    ("errors.py", "return self.issue.code", "return self.issue.code()"),
    ("errors.py", "super().__init__(message)", "super().other(message)"),
    ("errors.py", "path: str = \"\"", "path: str = factory()"),
    ("availability.py", "self._combat.query_action_availability",
     "getattr(self, '_combat').query_action_availability"),
])
def test_unsafe_form_does_not_gain_certificate(tmp_path, filename, old, new):
    config, _, target = setup(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    module = target / filename
    assert old in module.read_text()
    module.write_text(module.read_text().replace(old, new))
    result = build(config, offline=True, lexical_only=True)
    assert result["simple_python_certificate"] is None
    assert result["incremental"]["analysis_scope"]["mode"] in {
        "full-graph", "incremental-owners"}
    oracle(tmp_path, config, result)
