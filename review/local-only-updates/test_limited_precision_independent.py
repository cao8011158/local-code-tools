"""Independent guards: written annotation text alone does not prove its target."""
import copy
import json

import pytest

from tests.limited_precision_comparison import assert_limited_refinement
from tests.test_limited_precision_comparison import _fixture, REPO, PATH, KIND


def test_deferred_annotation_cannot_justify_a_new_eager_reference():
    actual, fresh, sources = _fixture()
    actual["unit_container_subscriptions"] = copy.deepcopy(fresh["unit_container_subscriptions"])
    sources[REPO, PATH] = "from __future__ import annotations\n" + sources[REPO, PATH]
    for snapshot in (actual, fresh):
        rows = []
        for row in snapshot["nodes"]:
            values = list(row)
            data = json.loads(values[4]); data["definition_line"] += 1
            values[4] = json.dumps(data); rows.append(tuple(values))
        snapshot["nodes"] = rows
    rows = []
    for row in actual["edges"]:
        values = list(row)
        if row[3] == "REFERENCES":
            data = json.loads(values[-1]); data["line"] += 1
            values[-1] = json.dumps(data)
        rows.append(tuple(values))
    actual["edges"] = rows
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, sources)


def test_later_same_name_class_cannot_replace_the_annotation_binding():
    actual, fresh, sources = _fixture()
    actual["unit_container_subscriptions"] = copy.deepcopy(fresh["unit_container_subscriptions"])
    sources[REPO, PATH] += "class Kind: pass\n"
    wrong = KIND + ".later"
    for snapshot in (actual, fresh):
        old = next(row for row in snapshot["nodes"] if row[0] == KIND)
        values = list(old); values[0] = wrong
        data = json.loads(values[4]); data.update(node_id=wrong, definition_line=6, version_id="later")
        values[4] = json.dumps(data); snapshot["nodes"].append(tuple(values)); snapshot["nodes"].sort()
    rows = []
    for row in actual["edges"]:
        values = list(row)
        if row[3] == "REFERENCES":
            values[2] = wrong
            data = json.loads(values[-1]); data["target_version_id"] = "later"
            values[-1] = json.dumps(data)
        rows.append(tuple(values))
    actual["edges"] = rows
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, sources)
