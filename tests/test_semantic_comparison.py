"""The oracle may forgive traversal but must detect changed graph evidence."""

import copy
import json

import pytest

from tests.semantic_comparison import assert_semantic_equal


def snapshot():
    site = {
        "site_id": "call:1", "execution_owner": "owner:1", "targets": ["target:1"],
        "complete": False, "unknown_origin": True,
        "unresolved_reasons": ["open-receiver-input"],
        "boundaries": [{"reason": "open-receiver-input", "path": "src/a.py", "line": 5}],
        "resolution_decision": {
            "reason": "matching-signals", "selected_targets": ["target:1"],
            "write_source_coverage": {
                "complete": False, "sources": [{"path": "src/a.py", "line": 3}],
                "gaps": ["unresolved-attribute-source",
                         {"reason": "missing-source", "path": "src/a.py", "line": 7}],
            },
        },
        "evidence": [
            {"tool": "jedi", "raw": [{"target": "target:1"}]},
            {"tool": "lct", "decision": {"selected_targets": ["target:1"],
             "write_source_coverage": {"gaps": ["unresolved-attribute-source"]}},
             "association_trace": {"steps": [{"expression": "candidate1"}]}},
        ],
    }
    return {
        "nodes": [("owner:1", "function"), ("target:1", "function")],
        "edges": [("owner:1", "target:1", "CALLS")],
        "sites": [("0", json.dumps(site))],
        "unit_source_supports": [("owner:1", "target:1", "src/a.py:3")],
        "unit_container_subscriptions": [("owner:1", "origin:1", "key:1")],
        "unit_container_writes": [("target:1", "origin:1", "key:1")],
        "value_reads": [("entry:1", "call:1")],
        "unit_analysis_reads": [("owner:1", "target:1", "jedi-target")],
        "unit_input_events": [("owner:1", "lexical-lookup")],
        "meta": {"origin_dependency_coverage": "observed-source-supports-partial"},
    }


def change_site(records, edit):
    result = copy.deepcopy(records)
    site = json.loads(result["sites"][0][1])
    edit(site)
    result["sites"] = [("0", json.dumps(site))]
    return result


def transitive(records, count=1, line=9):
    return change_site(records, lambda s: (
        s["resolution_decision"]["write_source_coverage"].update(
            rule="transitive-write-source-coverage",
            dependencies=[{"rule": "instance-field-coverage", "complete": False,
                           "sources": [{"path": "src/a.py", "line": line}],
                           "gaps": ["unresolved-attribute-source"] * count}]),
        s["evidence"][1]["decision"]["write_source_coverage"].update(
            rule="transitive-write-source-coverage",
            dependencies=[{"rule": "instance-field-coverage", "complete": False,
                           "sources": [{"path": "src/a.py", "line": line}],
                           "gaps": ["unresolved-attribute-source"] * count}])
    ))


def test_transitive_receipts_only_ignore_repeated_identical_gaps():
    assert_semantic_equal(transitive(snapshot(), 1), transitive(snapshot(), 100))
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(transitive(snapshot(), 1), transitive(snapshot(), 100, 10))


def test_identical_gap_repetitions_and_candidate_traversal_are_incidental():
    before = snapshot()
    after = change_site(before, lambda s: (
        s["resolution_decision"]["write_source_coverage"]["gaps"].extend(
            ["unresolved-attribute-source"] * 100 +
            [{"reason": "missing-source", "path": "src/a.py", "line": 7}] * 4),
        s["evidence"][1]["decision"]["write_source_coverage"]["gaps"].extend(
            ["unresolved-attribute-source"] * 50),
        s["evidence"][1]["association_trace"]["steps"].append(
            {"expression": "rejected constructor", "line": 99})))
    after["unit_analysis_reads"] = [("another", "producer", "jedi-target")]
    after["unit_input_events"] = []
    assert_semantic_equal(before, after)


@pytest.mark.parametrize("table,index", [
    ("nodes", 1), ("edges", 0), ("unit_source_supports", 0),
    ("unit_container_subscriptions", 0), ("unit_container_writes", 0),
    ("value_reads", 0),
])
def test_graph_and_source_dependencies_are_compared(table, index):
    before, after = snapshot(), snapshot()
    after[table][index] = ("different",)
    with pytest.raises(AssertionError, match=table):
        assert_semantic_equal(before, after)


@pytest.mark.parametrize("edit", [
    lambda s: s["targets"].append("target:2"),
    lambda s: s.update(complete=True),
    lambda s: s.update(unknown_origin=False),
    lambda s: s["unresolved_reasons"].clear(),
    lambda s: s["resolution_decision"].update(selected_targets=[]),
    lambda s: s["resolution_decision"]["write_source_coverage"].update(complete=True),
    lambda s: s["resolution_decision"]["write_source_coverage"]["gaps"].append(
        "different-reason"),
    lambda s: s["resolution_decision"]["write_source_coverage"]["gaps"].append(
        {"reason": "missing-source", "path": "src/other.py", "line": 7}),
    lambda s: s["resolution_decision"]["write_source_coverage"]["sources"].clear(),
    lambda s: s["boundaries"].clear(),
    lambda s: s["evidence"][0]["raw"].clear(),
    lambda s: s["evidence"][1]["decision"]["write_source_coverage"]["gaps"].append(
        {"reason": "unresolved-attribute-source", "path": "src/other.py", "line": 8}),
])
def test_site_semantics_and_distinct_diagnostics_are_compared(edit):
    before = snapshot()
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(before, change_site(before, edit))
