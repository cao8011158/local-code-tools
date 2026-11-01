"""Independent user contract: unresolved calls are results, not universal callers."""
import ast
import json
import runpy
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer, unknown
from lct.storage import current, manifest
from tests.test_call_candidate_index import analyzer
from tests.test_python_pipeline import analyze, site


@pytest.mark.parametrize("state", ["unqueried", "empty", "error", "inflight"])
def test_unresolved_call_is_not_a_caller_of_unrelated_target(tmp_path, state):
    a, target = analyzer(tmp_path)
    try:
        unresolved = next(s for s in a.sites if s["expression"] == "callback")
        if state == "error":
            module = a.module_for[unresolved["execution_owner"]]
            class FailedScript:
                def infer(self, *_):
                    raise RuntimeError("root synthetic frontend error")
            a.scripts[module] = FailedScript()
        if state in {"empty", "error"}:
            result = a.query(unresolved["execution_owner"], unresolved["_expr"])
            assert not result.atoms, "fixture must actually have no mapped target"
            assert result.reasons
        if state == "inflight":
            a._query_inflight = 1
        candidates = list(a.candidate_sites(target))
        assert unresolved not in candidates, "unresolved call was made a universal caller"
        if state != "error":
            assert any(s["expression"] == "target" for s in candidates), "known explicit call lost"
        assert unresolved in a.sites, "unresolved site must remain in the inventory"
    finally:
        a.close()


def test_jedi_target_survives_a_local_resolver_without_proof(tmp_path):
    original = Analyzer.resolve
    def no_local_answer(a, scope, expr, *args, **kwargs):
        if (a.nodes[scope]["qualname"] == "run" and isinstance(expr, ast.Name)
                and expr.id == "handler"):
            return unknown("root-synthetic-local-analysis-unknown")
        return original(a, scope, expr, *args, **kwargs)
    with patch.object(Analyzer, "resolve", no_local_answer):
        result = analyze(tmp_path, {
            "a.py": "from b import run\ndef first(): pass\nrun(first)\n",
            "b.py": "def run(handler):\n    handler()\n",
        }, closed=False)
    record = site(result, "handler", "run")
    names = {n["node_id"]: n["qualname"] for n in result[0]}
    inferred = {names[t] for t in record["resolution_decision"]["jedi_targets"]}
    assert inferred == {"first"}, "real Jedi must resolve the supplied callback"
    assert record["names"] == {"first"}, "local UNKNOWN discarded the real Jedi target"
    assert record["unknown_origin"] is True
    assert record["complete"] is False


def test_unknown_call_and_its_frontend_evidence_are_preserved(tmp_path):
    result = analyze(tmp_path, {"open.py": "def run(handler):\n    handler()\n"}, closed=False)
    record = site(result, "handler", "run")
    assert record["names"] == set()
    assert record["unknown_origin"] is True
    assert record["complete"] is False
    assert record["unresolved_reasons"]
    assert any(e["tool"] == "jedi" and "raw" in e for e in record["evidence"])


@pytest.mark.parametrize("noise", [0, 20])
def test_unknown_calls_are_not_enumerated_per_function_after_observation(tmp_path, noise):
    source = ("def first(): pass\ndef target(cb): cb()\ndef driver(): target(first)\n" +
              "".join(f"def idle_{i}(opaque): opaque()\n" for i in range(noise)))
    ns, trees = python_nodes(dict(repository="fixture", path="sample.py", text=source,
                                  sha256=digest(source), is_test=False))
    graph = Graph(ns, trees, [dict(name="fixture", path=str(tmp_path),
                                  head="captured", closed_world=False)])
    a = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    try:
        unresolved = set()
        for s in a.sites:
            if s["_call"] is not None:
                signal = a.query(s["execution_owner"], s["_expr"])
                if not signal.atoms:
                    unresolved.add(s["site_id"])
        assert len(unresolved) >= noise
        visits = []
        for n in ns:
            if n["kind"] != "function":
                continue
            for candidate in a.candidate_sites(n["node_id"]):
                if candidate["site_id"] in unresolved:
                    visits.append((n["qualname"], candidate["expression"]))
        assert visits == [], f"unknown pool enumerated per function: {visits[:8]}"
        target = next(n["node_id"] for n in ns if n["qualname"] == "target")
        assert any(s["expression"] == "target" for s in a.candidate_sites(target))
    finally:
        a.close()


@pytest.mark.parametrize("case", ["known-other-method", "unknown-method", "shadowing-parameter"])
def test_matching_spelling_does_not_establish_a_caller_relation(tmp_path, case):
    sources = {
        "known-other-method": "def work(): pass\nclass C:\n def work(self): pass\ndef caller(): C().work()\n",
        "unknown-method": "class C:\n def work(self): pass\nclass D:\n def work(self): pass\ndef caller(obj): obj.work()\n",
        "shadowing-parameter": "def work(): pass\ndef caller(work): work()\n",
    }
    text = sources[case]
    ns, trees = python_nodes(dict(repository="fixture", path="spell.py", text=text,
                                  sha256=digest(text), is_test=False))
    graph = Graph(ns, trees, [dict(name="fixture", path=str(tmp_path),
                                  head="captured", closed_world=False)])
    a = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    try:
        target_name = "C.work" if case == "unknown-method" else "work"
        target = next(n["node_id"] for n in ns if n["qualname"] == target_name)
        record = next(s for s in a.sites if s["expression"] in {"C().work", "obj.work", "work"})
        signal = a.query(record["execution_owner"], record["_expr"])
        if case == "known-other-method":
            assert {a.nodes[x.target]["qualname"] for x in signal.atoms} == {"C.work"}
        else:
            assert not signal.atoms
        assert record not in list(a.candidate_sites(target)), "name coincidence admitted an unrelated caller"
        assert not a.may_call(target, record), "a spelling match overrode the frontend result"
    finally:
        a.close()


def test_known_jedi_caller_keeps_argument_sources_and_updates_consumers(tmp_path):
    helpers = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                "local-only-updates/test_local_only_flow_independent.py"))
    sources = {
        "provider.py": "def first(): pass\ndef second(): pass\n",
        "worker.py": "def execute(callback): callback()\n",
        "caller.py": ("from provider import first, second\nfrom worker import execute\n"
                      "def redirect(fn): return execute\n@redirect\ndef alias(*args): pass\n"
                      "def run(): alias(first)\nrun()\n"),
    }
    c, repo = helpers["setup_sources"](tmp_path, sources)
    result = {"version": current(c)}
    previous = "first"
    for index, expected in enumerate(("first", "second", "first")):
        if index:
            path = repo / "src/caller.py"
            path.write_text(path.read_text().replace(f"alias({previous})", f"alias({expected})"))
            result = helpers["local_update"](c)
        assert helpers["call_targets"](c, result, "execute", "callback") == {expected}
        folder, _ = manifest(c, result["version"])
        with sqlite3.connect(folder / "graph-sites.sqlite") as db:
            supports = [json.loads(raw) for raw, in db.execute(
                "select data from unit_source_supports where kind='actual-parameter'")]
        assert any(s["producer_location"]["path"] == "src/caller.py"
                   and s["consumer_location"]["path"] == "src/worker.py"
                   and s["detail"]["parameter"]["name"] == "callback" for s in supports)
        previous = expected
