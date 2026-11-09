"""Bounded validation of typed evidence reuse across captured versions."""

from copy import deepcopy

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
                             selected_paths={("fixture", "src/a.py")})
    return prepared, ids, old_nodes, new_nodes


def nested_record(ident, node):
    version = node["version_id"]
    return {"evidence": [{"tool": "jedi", "raw": [{
        "mapping": "exact-captured-definition", "target": ident,
        "version_id": version, "source_sha256": node["source_sha256"],
        "column": 4, "full_name": "a.first", "line": 1,
        "module_path": "src/a.py", "name": "first", "repository": "fixture",
        "type": "function", "parameters": [{"name": "first"}, {"name": "second"}]}]}],
        "opaque": f"literal version_id={version} remains unchanged"}


def test_nested_typed_versions_are_rebound_without_mutating_old_record():
    ctx, ids, old, new = context()
    record = nested_record(ids["first"], old[ids["first"]])
    original = deepcopy(record)
    updated = ctx.rebind(record, owner_id=ids["owner"])
    raw = updated["evidence"][0]["raw"][0]
    assert raw["version_id"] == new[ids["first"]]["version_id"]
    assert raw["source_sha256"] == new[ids["first"]]["source_sha256"]
    assert raw["parameters"] == [{"name": "first"}, {"name": "second"}]
    assert updated["opaque"] == original["opaque"]
    assert record == original and updated is not record


def test_bad_stamp_unknown_schema_and_missing_target_fail_closed():
    ctx, ids, old, _ = context()
    record = nested_record(ids["first"], old[ids["first"]])
    record["evidence"][0]["raw"][0]["version_id"] = "tampered"
    with pytest.raises(EvidenceReuseRejected, match="stamp mismatch"):
        ctx.rebind(record, owner_id=ids["owner"])
    with pytest.raises(EvidenceReuseRejected, match="unknown version"):
        ctx.rebind({"mystery": {"target": ids["first"], "version_id": "old"}}, owner_id=ids["owner"])
    with pytest.raises(EvidenceReuseRejected, match="old definition missing"):
        ctx.rebind(nested_record("absent", old[ids["first"]]), owner_id=ids["owner"])


@pytest.mark.parametrize("new_source", [
    "def extra(): return 2\n",
    "def first(): return 1\ndef extra(): return 2\n",
    "\ndef first(): pass\ndef extra(): return 2\n",
])
def test_deleted_changed_or_relocated_definition_rejected(new_source):
    ctx, ids, old, _ = context(new_a=new_source)
    with pytest.raises(EvidenceReuseRejected):
        ctx.rebind(nested_record(ids["first"], old[ids["first"]]), owner_id=ids["owner"])


def test_ambiguous_definition_identity_rejects_retained_jedi_raw():
    ctx, ids, old, _ = context()
    first = old[ids["first"]]
    key = (first["repository"], first["path"], first["qualname"], first["kind"])
    ctx.new_by_key[key].append(deepcopy(ctx.new_by_key[key][0]))
    with pytest.raises(EvidenceReuseRejected, match="ambiguous or deleted"):
        ctx.rebind(nested_record(ids["first"], first), owner_id=ids["owner"])


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
    ctx.selected_paths.add(("fixture", "src/b.py"))
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


def test_retained_jedi_parameter_error_rebinds_without_inventing_parameters():
    ctx, ids, old, new = context()
    record = nested_record(ids["first"], old[ids["first"]])
    raw = record["evidence"][0]["raw"][0]
    raw["parameters"] = []
    raw["parameters_error"] = "RecursionError"
    original = deepcopy(record)
    rebound = ctx.rebind(record, owner_id=ids["owner"])
    current = rebound["evidence"][0]["raw"][0]
    assert current["parameters"] == []
    assert current["parameters_error"] == "RecursionError"
    assert current["version_id"] == new[ids["first"]]["version_id"]
    assert current["source_sha256"] == new[ids["first"]]["source_sha256"]
    assert record == original and rebound is not record


@pytest.mark.parametrize("damage", ["partial", "missing", "empty", "extra", "fingerprint"])
def test_malformed_or_unverified_jedi_parameter_error_fails_closed(damage):
    ctx, ids, old, _ = context()
    record = nested_record(ids["first"], old[ids["first"]])
    raw = record["evidence"][0]["raw"][0]
    raw["parameters"] = []
    raw["parameters_error"] = "RecursionError"
    if damage == "partial":
        raw["parameters"] = [{"name": "partly computed"}]
    elif damage == "missing":
        del raw["parameters"]
    elif damage == "empty":
        raw["parameters_error"] = ""
    elif damage == "extra":
        raw["resolver_fallback"] = True
    else:
        raw["source_sha256"] = "unverified"
    with pytest.raises(EvidenceReuseRejected):
        ctx.rebind(record, owner_id=ids["owner"])


@pytest.mark.parametrize("proof", [None, (), ("one",), ("wrong", "wrong"), ("", "")])
def test_source_only_rebinding_requires_two_matching_captured_hashes(proof):
    _, ids, old, new = context()
    owner = ids["owner"]
    source = old[owner]["source_sha256"]
    ctx = RebindContext(old_nodes=old, new_nodes=new, old_trees={}, new_trees={},
                        selected_paths={("fixture", "src/a.py")},
                        verified_sources={("fixture", "src/b.py"): proof} if proof is not None else {})
    with pytest.raises(EvidenceReuseRejected, match="source not verified"):
        ctx.rebind(nested_record(owner, old[owner]), owner_id=owner)
    ctx = RebindContext(old_nodes=old, new_nodes=new, old_trees={}, new_trees={},
                        selected_paths={("fixture", "src/a.py")},
                        verified_sources={("fixture", "src/b.py"): (source, source)})
    assert ctx.rebind(nested_record(owner, old[owner]), owner_id=owner)
