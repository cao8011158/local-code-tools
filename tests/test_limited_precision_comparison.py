"""Historical budget comparator now requires exact full/current semantics."""

import copy

import pytest

from tests.limited_precision_comparison import assert_limited_refinement
from tests.test_semantic_comparison import snapshot


def test_identical_source_and_graph_accept():
    current = snapshot()
    assert_limited_refinement(current, copy.deepcopy(current), {})


@pytest.mark.parametrize("table", ("sites", "edges", "unit_source_supports",
                                   "unit_container_subscriptions", "unit_container_writes"))
def test_source_and_graph_mismatch_rejected(table):
    current, fresh = snapshot(), snapshot()
    current[table] = []
    with pytest.raises(AssertionError, match=table):
        assert_limited_refinement(current, fresh, {})
