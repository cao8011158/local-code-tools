"""Planner comparisons do not depend on a checkout or invoke the analyzer."""

import json

import pytest

from lct.incremental import plan_update


def capture(files=(), *, head="a", branch="main", pins=None, config="c", program="p"):
    return dict(
        files=[dict(repository="repo", path=path, sha256=sha, is_test=False) for path, sha in files],
        repositories=[dict(name="repo", head=head, branch=branch, path="/captured", status="")],
        dependency_pins={} if pins is None else pins,
        config_hash=config,
        program_hash=program,
    )


def test_no_op_is_machine_readable():
    old = capture([("src/a.py", "1"), ("docs/a.md", "2")])
    plan = plan_update(old, old)
    assert json.loads(json.dumps(plan)) == plan
    assert (plan["change_kind"], plan["analysis_scope"], plan["reasons"]) == ("no-op", "none", [])
    assert not plan["full_analysis_required"]
    assert not plan["affected_embedding_partitions"]


def test_python_change_requires_full_analysis_even_if_only_one_file_changed():
    plan = plan_update(capture([("src/a.py", "1"), ("src/b.py", "2")]),
                       capture([("src/a.py", "3"), ("src/b.py", "2")]))
    assert plan["changed"][0]["path"] == "src/a.py"
    assert plan["change_kind"] == "python-change"
    assert plan["analysis_scope"] == "full-capture"
    assert "dependency-closure-unavailable" in plan["reasons"]
    assert {p["kind"] for p in plan["affected_embedding_partitions"]} == {"module", "class", "function"}


def test_docs_only_still_changes_repository_wide_python_version_identity():
    plan = plan_update(capture([("src/a.py", "1"), ("docs/a.md", "2")]),
                       capture([("src/a.py", "1"), ("docs/a.md", "3")]))
    assert plan["change_kind"] == "docs-only"
    assert plan["full_analysis_required"]
    assert "documentation-changed-repository-identity" in plan["reasons"]
    assert plan["affected_embedding_partitions"] == [dict(repository="repo", kind="documentsection", is_test=False)]


def test_revision_only_and_dependency_pin_and_config_changes():
    old = capture([("src/a.py", "1")])
    revised = plan_update(old, capture([("src/a.py", "1")], head="b", branch="feature"))
    assert revised["change_kind"] == "metadata-only"
    assert "repository-revision-changed:repo" in revised["reasons"]
    assert revised["full_analysis_required"] and not revised["affected_embedding_partitions"]
    pin = plan_update(old, capture([("src/a.py", "1")], pins={"engine": "new"}))
    assert "dependency-pins-changed" in pin["reasons"]
    assert pin["full_analysis_required"]
    config = plan_update(old, capture([("src/a.py", "1")], config="new"))
    assert "config-changed" in config["reasons"]
    assert dict(repository="*", kind="*", is_test="*") in config["affected_embedding_partitions"]


def test_add_delete_and_rename_are_explicit_not_inferred():
    old = capture([("src/old.py", "same"), ("docs/gone.md", "x")])
    new = capture([("src/new.py", "same"), ("docs/new.md", "y")])
    plan = plan_update(old, new)
    assert {(x["path"], x["change"]) for x in plan["changed"]} == {
        ("src/new.py", "added"), ("docs/new.md", "added")}
    assert {x["path"] for x in plan["removed"]} == {"src/old.py", "docs/gone.md"}
    assert plan["analysis_scope"] == "full-capture"


def test_missing_pin_attestation_and_duplicate_file_fail_closed():
    old = capture([("src/a.py", "1")])
    new = capture([("src/a.py", "1")])
    del new["dependency_pins"]
    with pytest.raises(ValueError, match="dependency_pins"):
        plan_update(old, new)
    with pytest.raises(ValueError, match="duplicate"):
        plan_update(old, capture([("src/a.py", "1"), ("src/a.py", "2")]))


def test_same_bytes_changed_test_partition_is_not_no_op():
    old = capture([("src/a.py", "1")])
    new = capture([("src/a.py", "1")])
    new["files"][0]["is_test"] = True
    plan = plan_update(old, new)
    assert plan["changed"][0]["change"] == "metadata"
    assert plan["analysis_scope"] == "full-capture"
    assert {p["is_test"] for p in plan["affected_embedding_partitions"]} == {False, True}


@pytest.mark.parametrize("field", ["head", "branch"])
def test_missing_repository_revision_is_not_no_op(field):
    old = capture()
    new = capture()
    del new["repositories"][0][field]
    with pytest.raises(ValueError, match="head or branch"):
        plan_update(old, new)


@pytest.mark.parametrize("field", ["config_hash", "program_hash"])
def test_missing_or_empty_build_identity_is_not_no_op(field):
    old = capture()
    new = capture()
    new[field] = ""
    with pytest.raises(ValueError, match=field):
        plan_update(old, new)
