"""The oracle compares tool observations, uncertainty and source provenance."""

import copy
import json

import pytest

from tests.semantic_comparison import assert_semantic_equal


def snapshot():
    site = dict(site_id="call:1", execution_owner="owner:1", targets=["target:1"],
                complete=False, unknown_origin=True, unresolved_reasons=["jedi-no-result"],
                boundaries=[], target_provider="jedi-get-signatures",
                evidence=[{"tool": "ast", "role": "site and execution phase"},
                          {"tool": "jedi", "api": "get_signatures", "position": [5, 13],
                           "raw": [{"name": "target", "line": 2,
                                    "mapping": "exact-captured-definition"}]}])
    return dict(nodes=[("owner:1", "function"), ("target:1", "function")],
                edges=[("owner:1", "target:1", "CALLS")],
                sites=[("0", json.dumps(site))],
                unit_source_supports=[("owner:1", "target:1", "src/a.py:3")],
                unit_container_subscriptions=[("owner:1", "origin:1", "key:1")],
                unit_container_writes=[("target:1", "origin:1", "key:1")],
                unit_analysis_reads=[("owner:1", "target:1", "jedi-target")],
                unit_input_events=[("owner:1", "lexical-lookup")],
                meta={"origin_dependency_coverage": "source-only"})


def change_site(records, edit):
    result = copy.deepcopy(records)
    record = json.loads(result["sites"][0][1])
    edit(record)
    result["sites"] = [("0", json.dumps(record))]
    return result


def test_owner_work_ledgers_may_differ_without_semantic_change():
    before, after = snapshot(), snapshot()
    after["unit_analysis_reads"] = [("another", "producer", "jedi-target")]
    after["unit_input_events"] = []
    assert_semantic_equal(before, after)


def test_jedi_raw_candidate_permutation_is_semantically_equal():
    before = change_site(snapshot(), lambda s: s["evidence"][1]["raw"].append(
        {"name": "other", "parameters": ["first", "second"], "mapping": "external-or-excluded"}))
    after = change_site(before, lambda s: s["evidence"][1]["raw"].reverse())
    assert_semantic_equal(before, after)


@pytest.mark.parametrize("edit", (
    lambda rows: rows.pop(),
    lambda rows: rows[0].update(line=99),
    lambda rows: rows[1]["parameters"].reverse(),
))
def test_jedi_raw_multiplicity_fields_and_parameter_order_remain_semantic(edit):
    before = change_site(snapshot(), lambda s: s["evidence"][1]["raw"].append(
        {"name": "other", "parameters": ["first", "second"], "mapping": "external-or-excluded"}))
    after = change_site(before, lambda s: edit(s["evidence"][1]["raw"]))
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(before, after)


@pytest.mark.parametrize("table,index", [
    ("nodes", 1), ("edges", 0), ("unit_source_supports", 0),
    ("unit_container_subscriptions", 0), ("unit_container_writes", 0),
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
    lambda s: s["boundaries"].append({"full_name": "external"}),
    lambda s: s["evidence"][1]["raw"].clear(),
    lambda s: s["evidence"][1].update(position=[5, 12]),
    lambda s: s.update(target_provider="lct-solver"),
])
def test_site_semantics_raw_position_and_distinct_diagnostics_are_compared(edit):
    before = snapshot()
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(before, change_site(before, edit))
