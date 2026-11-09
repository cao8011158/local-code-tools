"""Indexed callers follow actual Jedi observations, not unknown spelling buckets."""

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze, site


def analyzer(tmp_path, text):
    nodes, trees = python_nodes(dict(repository="fixture", path="demo.py", text=text,
                                    sha256=digest(text), is_test=False))
    graph = Graph(nodes, trees, [dict(name="fixture", path=str(tmp_path),
                                 head="captured", closed_world=False)])
    return Analyzer(graph.nodes, trees, graph.repos, graph.imported)


def test_alias_and_direct_call_use_mapped_jedi_signatures(tmp_path):
    source = "def target(): pass\ndef other(): pass\ndef run(opaque):\n alias=target\n alias()\n target()\n opaque()\n other()\n"
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    assert site(graph, "alias", "run")["names"] == {"target"}
    assert site(graph, "target", "run")["names"] == {"target"}
    assert site(graph, "other", "run")["names"] == {"other"}
    unknown = site(graph, "opaque", "run")
    assert unknown["targets"] == [] and unknown["unknown_origin"]
    for expression in ("alias", "target", "opaque", "other"):
        observed = site(graph, expression, "run")
        assert observed["target_provider"] == "jedi-get-signatures"
        assert observed["evidence"][1]["api"] == "get_signatures"


def test_failed_jedi_signature_keeps_site_and_error(tmp_path):
    a = analyzer(tmp_path, "def target(): pass\ndef run(callback): callback()\n")
    try:
        call = next(s for s in a.sites if s["expression"] == "callback")
        module = a.module_for[call["execution_owner"]]

        class FailedScript:
            def get_signatures(self, *_):
                raise RuntimeError("synthetic Jedi failure")

        a.scripts[module] = FailedScript()
        result = a.query(call["execution_owner"], call["_call"], signature=True)
        assert not result.atoms and "jedi-error:RuntimeError" in result.reasons
    finally:
        a.close()


@pytest.mark.parametrize("noise", (0, 20, 100))
def test_unrelated_unknown_calls_do_not_become_candidate_targets(tmp_path, noise):
    source = ("def first(): pass\ndef target(cb): cb()\ndef driver(): target(first)\n" +
              "".join(f"def idle_{i}(opaque): opaque()\n" for i in range(noise)))
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    assert site(graph, "target", "driver")["names"] == {"target"}
    assert site(graph, "cb", "target")["names"] == {"first"}
    for i in range(noise):
        s = site(graph, "opaque", f"idle_{i}")
        assert s["targets"] == [] and "jedi-no-result" in s["unresolved_reasons"]
    assert graph[2]["jedi_raw_result_counts"].get("empty", 0) >= noise


def test_selected_owner_expansion_preserves_local_query_reuse(tmp_path):
    a = analyzer(tmp_path, "def first(): pass\ndef second(): pass\ndef one(): first()\ndef two(): second()\n")
    try:
        owners = {n["qualname"]: i for i, n in a.nodes.items()}
        a.prepare_site_queries({owners["one"]})
        initial = a.executed_queries
        assert initial == 1
        a.prepare_site_queries({owners["one"], owners["two"]})
        assert a.executed_queries == initial + 1
        assert a.query_cache_hits >= 1
    finally:
        a.close()
