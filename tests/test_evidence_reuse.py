"""Bounded validation of typed evidence reuse across captured versions."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from lct.evidence_reuse import EvidenceReuseRejected, RebindContext
from lct.extract import python_nodes


OLD_A = "def first(): pass\ndef extra(): return 1\n"
NEW_A = "def first(): pass\ndef extra(): return 2\n"
B = "from a import first\ndef owner(): first()\n"


def context(old_a=OLD_A, new_a=NEW_A):
    def capture(a):
        nodes, trees = [], {}
        for path, source in (("src/a.py", a), ("src/b.py", B)):
            group, asts = python_nodes(dict(repository="fixture", path=path,
                                            text=source, is_test=False))
            nodes.extend(group)
            trees.update(asts)
        return {n["node_id"]: n for n in nodes}, trees
    old_nodes, old_trees = capture(old_a)
    new_nodes, new_trees = capture(new_a)
    ids = {n["qualname"]: ident for ident, n in old_nodes.items()}
    prepared = RebindContext(old_nodes=old_nodes, new_nodes=new_nodes,
                             old_trees=old_trees, new_trees=new_trees,
                             selected_paths={"src/a.py"})
    return prepared, ids, old_nodes, new_nodes


def nested_record(ident, node):
    version = node["version_id"]
    return {"resolution_decision": {
        "call_access": {"definitions": [{"target": ident, "version_id": version}],
                        "unused_inputs": {"dependencies": [{"evidence": [{
                            "reason": "definition-dependencies", "function": ident,
                            "call_line": 2, "invocation_scope": "owner", "version_id": version}]}]}},
        "opaque": f"literal version_id={version} remains unchanged"}}


def test_nested_typed_versions_are_rebound_without_mutating_old_record():
    ctx, ids, old, new = context()
    record = nested_record(ids["first"], old[ids["first"]])
    original = deepcopy(record)
    updated = ctx.rebind(record, owner_id=ids["owner"])
    proof = updated["resolution_decision"]
    assert proof["call_access"]["definitions"][0]["version_id"] == new[ids["first"]]["version_id"]
    assert proof["call_access"]["unused_inputs"]["dependencies"][0]["evidence"][0]["version_id"] == new[ids["first"]]["version_id"]
    assert proof["opaque"] == original["resolution_decision"]["opaque"]
    assert record == original and updated is not record


def test_bad_stamp_unknown_schema_and_missing_target_fail_closed():
    ctx, ids, old, _ = context()
    record = nested_record(ids["first"], old[ids["first"]])
    record["resolution_decision"]["call_access"]["definitions"][0]["version_id"] = "tampered"
    with pytest.raises(EvidenceReuseRejected, match="stamp mismatch"):
        ctx.rebind(record, owner_id=ids["owner"])
    with pytest.raises(EvidenceReuseRejected, match="unknown version"):
        ctx.rebind({"mystery": {"target": ids["first"], "version_id": "old"}}, owner_id=ids["owner"])
    with pytest.raises(EvidenceReuseRejected, match="old definition missing"):
        ctx.rebind({"definitions": [{"target": "absent", "version_id": "old"}]}, owner_id=ids["owner"])


@pytest.mark.parametrize("new_source", [
    "def extra(): return 2\n",
    "def first(): return 1\ndef extra(): return 2\n",
    "\ndef first(): pass\ndef extra(): return 2\n",
])
def test_deleted_changed_or_relocated_definition_rejected(new_source):
    ctx, ids, old, _ = context(new_a=new_source)
    with pytest.raises(EvidenceReuseRejected):
        ctx.rebind(nested_record(ids["first"], old[ids["first"]]), owner_id=ids["owner"])


def test_owner_invalidation_and_repeated_lookup_use_prepared_index_only():
    ctx, ids, old, _ = context()
    record = nested_record(ids["first"], old[ids["first"]])
    class PreparedOnly(dict):
        def values(self):
            raise AssertionError("node table scanned after context preparation")
    ctx.old_nodes = PreparedOnly(ctx.old_nodes)
    ctx.new_nodes = PreparedOnly(ctx.new_nodes)
    ctx.rebind(record, owner_id=ids["owner"])
    first_count = ctx.match_evaluations
    ctx.rebind(record, owner_id=ids["owner"])
    assert ctx.match_evaluations == first_count == 2
    ctx.selected_paths.add("src/b.py")
    with pytest.raises(EvidenceReuseRejected, match="owner selected"):
        ctx.rebind(record, owner_id=ids["owner"])


def test_raw_mapping_checks_both_old_stamps_and_rebinds_source_fingerprint():
    ctx, ids, old, new = context()
    ident = ids["first"]
    record = {"raw": [{"mapping": "exact-captured-definition", "target": ident,
                       "version_id": old[ident]["version_id"],
                       "source_sha256": old[ident]["source_sha256"],
                       "column": 0, "full_name": "a.first", "line": 1,
                       "module_path": "src/a.py", "name": "first",
                       "repository": "fixture", "type": "function"}]}
    updated = ctx.rebind(record, owner_id=ids["owner"])["raw"][0]
    assert updated["version_id"] == new[ident]["version_id"]
    assert updated["source_sha256"] == new[ident]["source_sha256"]
    record["raw"][0]["source_sha256"] = "tampered"
    with pytest.raises(EvidenceReuseRejected, match="raw source fingerprint mismatch"):
        ctx.rebind(record, owner_id=ids["owner"])


def test_v5_reanalyzes_owner_after_tampered_retained_evidence():
    path = (Path(__file__).resolve().parents[1] / "review/batch4-incremental"
            / "directional-experiment/v5.py")
    spec = importlib.util.spec_from_file_location("v5_evidence_test", path)
    v5 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v5)
    _, before, after = next(c for c in v5.constructor_cases()
                            if c[0] == "same_named_initializers_isolated")
    old = v5.v1.local.build(before)
    old = deepcopy(old)
    site = next(s for s in old["info"]["sites"]
                if ":src/c.py:" in s["execution_owner"] and s.get("resolution_decision"))
    def tamper(value):
        if isinstance(value, dict):
            if "version_id" in value:
                value["version_id"] = "tampered"
                return True
            return any(tamper(v) for v in value.values())
        if isinstance(value, list):
            return any(tamper(v) for v in value)
        return False
    assert tamper(site)
    candidate, cost = v5.candidate(before, after, old)
    assert cost["rejected_owner_paths"] == ["src/c.py"]
    assert "src/c.py" in cost["selected"]
    assert v5.v1.local.normalized(candidate) == v5.v1.local.normalized(v5.v1.local.build(after))
