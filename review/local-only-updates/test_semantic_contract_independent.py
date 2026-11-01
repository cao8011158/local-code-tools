"""Root-owned tests: real rejected-candidate receipt and retained source facts."""
import copy
import json

import pytest

from tests.semantic_comparison import assert_semantic_equal


def receipt(gaps, trace):
    coverage = dict(rule="instance-field-coverage", complete=False,
                    events=[], sources=[], checks=[], gaps=gaps)
    decision = dict(write_source_coverage=copy.deepcopy(coverage), reason="unknown")
    site = dict(site_id="availability:9:15", execution_owner="AvailabilityRuntime.query_action_availability",
                targets=[], boundaries=[], unknown_origin=True, complete=False,
                unresolved_reasons=["jedi-no-result", "open-receiver-input"],
                resolution_decision=decision,
                evidence=[dict(tool="lct", decision=copy.deepcopy(decision),
                               association_trace=dict(steps=trace, truncated=False))])
    return {"sites": [("0", json.dumps(site))],
            "unit_source_supports": [("provider.run", "callback:1", "consumer.execute", "call:2")],
            "unit_container_subscriptions": [("handlers", "go", "consumer.run")],
            "unit_container_writes": [("handlers", "go", "provider.configure")],
            "analysis_reads": [("combat", "errors", "jedi-target")]}


def test_rejected_candidate_trace_and_repeated_receipt_do_not_make_new_dependency():
    local = receipt(["unresolved-attribute-source"] * 122,
                    [dict(scope="availability", expression="self._combat")])
    fresh = receipt(["unresolved-attribute-source"] * 1134,
                    [dict(scope="availability", expression="self._combat"),
                     dict(scope="combat", expression="StateMachineError", rule="candidate-query")])
    local["unit_analysis_reads"] = []
    fresh["unit_analysis_reads"] = [("availability.method", "combat", "errors", "jedi-target")]
    assert_semantic_equal(local, fresh)


@pytest.mark.parametrize("table", ["unit_source_supports", "unit_container_subscriptions",
                                   "unit_container_writes", "analysis_reads"])
def test_missing_actual_source_or_subscription_is_still_rejected(table):
    expected = receipt(["unresolved-attribute-source"], [])
    actual = copy.deepcopy(expected)
    actual[table] = []
    with pytest.raises(AssertionError, match=table):
        assert_semantic_equal(actual, expected)


def test_equal_unknown_targets_do_not_hide_different_source_location():
    a = receipt([dict(reason="unresolved-attribute-source", path="a.py", line=10)], [])
    b = receipt([dict(reason="unresolved-attribute-source", path="a.py", line=11)], [])
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(a, b)


def test_nested_decision_accepted_target_cannot_be_erased_with_trace():
    expected = receipt([], [])
    actual = copy.deepcopy(expected)
    site = json.loads(actual["sites"][0][1])
    site["evidence"][0]["decision"]["selected_targets"] = ["different.function"]
    actual["sites"] = [("0", json.dumps(site))]
    with pytest.raises(AssertionError, match="sites"):
        assert_semantic_equal(actual, expected)


def test_transitive_receipt_duplicate_gap_is_also_only_repetition():
    actual, expected = receipt([], []), receipt([], [])
    for snapshot, count in ((actual, 2), (expected, 7)):
        site = json.loads(snapshot["sites"][0][1])
        for decision in (site["resolution_decision"], site["evidence"][0]["decision"]):
            decision["write_source_coverage"] = dict(
                rule="transitive-write-source-coverage", complete=False,
                dependencies=[dict(rule="instance-field-coverage", complete=False,
                                   gaps=["unresolved-attribute-source"] * count)])
        snapshot["sites"] = [("0", json.dumps(site))]
    assert_semantic_equal(actual, expected)
