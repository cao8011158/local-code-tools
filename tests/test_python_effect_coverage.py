"""Execution-site inventory remains source grounded after effect adjudication exits."""

import pytest

from tests.test_python_pipeline import analyze, site


def source(body, operation="obj.change()", asynchronous=False):
    return f"""def a(): pass
def b(): pass
class C:
 def __init__(receiver): receiver.run=a
 {"async " if asynchronous else ""}def change(receiver):
  {body}
async def caller(flag,consume):
 obj=C()
 {operation}
 obj.run()
"""


AWAIT_FORMS = [
    "await obj.change()",
    "value=await obj.change()",
    "if await obj.change(): pass",
    "consume(await obj.change())",
    "value=(await obj.change(),)",
    "value=flag and await obj.change()",
    "pending=obj.change()\n if await pending: pass",
]


@pytest.mark.parametrize("operation", AWAIT_FORMS)
def test_nested_await_call_keeps_lexical_execution_owner_and_location(tmp_path, operation):
    result = analyze(tmp_path, {"demo.py": source("receiver.run=b", operation, True)}, closed=False)
    nested = site(result, "obj.change", "caller")
    field = site(result, "obj.run", "caller")
    assert nested["phase"] == field["phase"] == "body"
    assert nested["line"] <= field["line"]
    assert nested["target_provider"] == field["target_provider"] == "jedi-get-signatures"
    assert nested["evidence"][1]["api"] == "get_signatures"
    assert "resolution_decision" not in field


def test_defaults_belong_to_definition_scope_and_deferred_bodies_to_their_owner(tmp_path):
    text = """def a(): pass
async def caller(obj):
 async def nested():
  await obj.change()
 callback=lambda: obj.change()
 def f(cb=obj.change()): pass
 obj.run()
"""
    result = analyze(tmp_path, {"demo.py": text}, closed=False)
    records = result[2]["sites"]
    names = {n["node_id"]: n["qualname"] for n in result[0]}
    calls = [(names[s["execution_owner"]], s["phase"], s["expression"])
             for s in records if s["kind"] == "call"]
    assert ("caller.nested", "body", "obj.change") in calls
    assert ("caller", "definition", "obj.change") in calls
    assert ("caller", "body", "obj.run") in calls
    assert any(owner.startswith("caller") and "lambda" in owner and expression == "obj.change"
               for owner, _, expression in calls)


@pytest.mark.parametrize("mutation", ("obj.run: object=b", "obj.run += b", "del obj.run", "obj.run=b"))
def test_source_writes_keep_their_location_without_target_certification(tmp_path, mutation):
    result = analyze(tmp_path, {"demo.py": source("pass", mutation)}, closed=False)
    records = result[2]["_unit_writes"]
    assert any(row["producer_location"]["expression"] == "obj.run" and
               row["kind"] == "field-write" and row["key"] == "string:run"
               for row in records)
    assert all("target" not in row and "expected_target" not in row for row in records)


@pytest.mark.parametrize("body", ("receiver.run=b", "receiver: object\n  receiver.run=b"))
def test_observed_field_call_is_jedi_owned(tmp_path, body):
    field = site(analyze(tmp_path, {"demo.py": source(body)}, closed=False), "obj.run", "caller")
    assert field["target_provider"] == "jedi-get-signatures"
    assert field["evidence"][1]["api"] == "get_signatures"
    assert "resolution_decision" not in field


RECEIVER_BINDINGS = [
    ("receiver=other\n  receiver.run=b", {"a"}),
    ("del receiver\n  receiver.run=b", {"a"}),
    ("receiver: object=other\n  receiver.run=b", {"a"}),
    ("receiver,other=(other,receiver)\n  receiver.run=b", {"a"}),
    ("receiver.run=b", {"a", "b"}),
    ("receiver: object\n  receiver.run=b", {"a"}),
    ("return\n  receiver=other\n  receiver.run=b", {"a"}),
    ("receiver.run=b\n  return\n  del receiver", {"a", "b"}),
    ("local=a\n  receiver.run=b", {"a", "b"}),
]


@pytest.mark.parametrize("body,expected", RECEIVER_BINDINGS)
def test_receiver_binding_sources_do_not_arbitrate_jedi_result(tmp_path, body, expected):
    import jedi
    text = source(body)
    assert {n.name for n in jedi.Script(text).get_signatures(len(text.splitlines()), 9)} == expected
    graph = analyze(tmp_path, {"demo.py": text}, closed=False)
    observed = site(graph, "obj.run", "caller")
    assert observed["names"] == expected
    assert "resolution_decision" not in observed
    assert any(row["key"] == "string:run" for row in graph[2]["_unit_subscriptions"])
