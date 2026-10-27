"""With protocols enter after each context expression and exit after the suite."""

import pytest

from tests.test_python_pipeline import analyze, site


HEADER = """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
"""


@pytest.mark.parametrize(
    "operation,asynchronous,enter_body,exit_body,uncertain,regions",
    [
        ("with Manager() as resource:\n  obj.run()", False, "obj.run=b", "pass", True, 1),
        ("async with Manager() as resource:\n  obj.run()", True, "obj.run=b", "pass", True, 1),
        ("with Manager(), Manager(obj.run()):\n  pass", False, "obj.run=b", "pass", True, 1),
        ("with Manager(obj.run()):\n  pass", False, "obj.run=b", "pass", False, 0),
        ("with Manager():\n  pass\n obj.run()", False, "pass", "obj.run=b", True, 2),
    ],
    ids=["with-body", "async-with-body", "second-context", "first-context", "after-exit"],
)
def test_region_entry_order(
    tmp_path, operation, asynchronous, enter_body, exit_body, uncertain, regions
):
    modifier = "async " if asynchronous else ""
    enter = "__aenter__" if asynchronous else "__enter__"
    exit_ = "__aexit__" if asynchronous else "__exit__"
    text = HEADER + f"""{modifier}def caller():
 obj=C()
 class Manager:
  def __init__(self,value=None): pass
  {modifier}def {enter}(self):
   {enter_body}
  {modifier}def {exit_}(self,*args):
   {exit_body}
 {operation}
"""
    result = analyze(tmp_path, {"demo.py": text}, closed=False)
    s = site(result, "obj.run", "caller")
    assert s["names"] == {"a"} and "b" not in s["names"]
    assert s["unknown_origin"] is uncertain
    assert s["complete"] is (not uncertain)
    assert s["phase"] == "body"
    assert text.splitlines()[s["line"] - 1][s["column"] :].startswith("obj.run")
    if uncertain:
        assert "unsupported-protocol-region" in s["unresolved_reasons"]
        assert not s["resolution_decision"]["excluded_jedi_targets"]
    else:
        assert not s["unresolved_reasons"]
    receipt = s["resolution_decision"]["write_source_coverage"]
    syntax = "AsyncWith" if asynchronous else "With"
    observed = {
        c["event_id"]
        for c in receipt["checks"]
        if c["event_kind"] == "region" and c["syntax"] == syntax
    }
    # A body/second context sees entry only; a following read also sees exit.
    assert len(observed) == regions
    nodes = {n["node_id"]: n for n in result[0]}
    assert nodes[s["lexical_owner"]]["qualname"] == "caller"
    calls = [
        e for e in result[1] if e["kind"] == "CALLS" and e.get("site_id") == s["site_id"]
    ]
    assert {nodes[e["target"]]["qualname"] for e in calls} == {"a"}
    assert all(
        e["source"] == s["execution_owner"]
        and e["line"] == s["line"]
        and e["column"] == s["column"]
        and e["unknown_origin"] is uncertain
        and e["complete"] is (not uncertain)
        for e in calls
    )
