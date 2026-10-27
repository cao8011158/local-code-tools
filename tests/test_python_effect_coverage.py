"""Mechanism contracts for scope events, receiver stability and independent coverage."""

import ast

import pytest

from lct.graph import Graph
from lct.python_analysis import Analyzer, certified, known
from lct.python_effects import EffectCoverage, EffectEvent, EffectKind, EffectOutcome
from tests.test_python_pipeline import analyze, site
from tests.test_python_review_round3 import check


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


@pytest.mark.parametrize(
    "binding",
    ["receiver=other", "del receiver", "receiver: object=other", "receiver,other=(other,receiver)"],
)
def test_receiver_binding_invalidates_summary(tmp_path, binding):
    text = source(binding + "\n  receiver.run=b")
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "receiver-binding-changed" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


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
def test_await_position_matrix(tmp_path, operation):
    text = source("receiver.run=b", operation, asynchronous=True)
    s = check(
        analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", set(), {"a", "b"}, True
    )
    assert "deferred-method-resumption-not-modeled" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("receiver.run=b", {"b"}),
        ("receiver: object\n  receiver.run=b", {"b"}),
        ("return\n  receiver=other\n  receiver.run=b", {"a"}),
        ("receiver.run=b\n  return\n  del receiver", {"b"}),
        ("local=a\n  receiver.run=b", {"b"}),
    ],
)
def test_straight_line_binding_controls(tmp_path, body, expected):
    check(
        analyze(tmp_path, {"demo.py": source(body)}, closed=False),
        "obj.run",
        expected,
        {"a", "b"} - expected,
    )


@pytest.mark.parametrize("constructor", [True, False])
def test_constructor_and_method_share_stability_check(tmp_path, constructor):
    text = source("receiver=other\n  receiver.run=b")
    if constructor:
        text = text.replace(
            "def __init__(receiver): receiver.run=a",
            "def __init__(receiver):\n  receiver=other\n  receiver.run=b",
        ).replace(" obj.change()", " pass")
        s = site(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", "caller")
        assert not s["complete"] and s["unknown_origin"]
        assert "receiver-binding-changed" in s["unresolved_reasons"]
        assert not s["names"]
    else:
        check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def analyzer_for(tmp_path, text):
    """Create an isolated snapshot analyzer without running analyzed code."""
    from lct.common import digest
    from lct.extract import python_nodes

    nodes, trees = python_nodes(
        dict(repository="fixture", path="demo.py", text=text, is_test=False, sha256=digest(text))
    )
    graph = Graph(nodes, trees, [dict(name="fixture", path=str(tmp_path), closed_world=False)])
    return Analyzer(graph.nodes, graph.asts, graph.repos, graph.imported)


@pytest.mark.parametrize("operation", AWAIT_FORMS)
def test_collector_records_nested_operands_in_execution_scope(tmp_path, operation):
    text = source("receiver.run=b", operation, asynchronous=True)
    a = analyzer_for(tmp_path, text)
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        events = a.effects.by_scope[scope]
        waits = [e for e in events if e.kind == "await"]
        calls = [e for e in events if e.kind == "call" and ast.unparse(e.node.func) == "obj.change"]
        assert len(waits) == len(calls) == 1
        assert waits[0].scope == calls[0].scope == scope
        assert waits[0].phase == "body"
        assert calls[0].order < waits[0].order
        assert waits[0].conditional is (operation.startswith("value=flag"))
        assert len({e.ident for e in events}) == len(events)
    finally:
        a.close()


def test_collector_scopes_defaults_and_uninvoked_bodies(tmp_path):
    text = """def a(): pass
async def caller(obj):
 async def nested():
  await obj.change()
 callback=lambda: obj.change()
 def f(cb=obj.change()): pass
 obj.run()
"""
    a = analyzer_for(tmp_path, text)
    try:
        byname = {n["qualname"]: i for i, n in a.nodes.items()}
        caller = a.effects.by_scope[byname["caller"]]
        assert not any(e.kind == "await" for e in caller)
        calls = [e for e in caller if e.kind == "call" and ast.unparse(e.node.func) == "obj.change"]
        assert len(calls) == 1 and calls[0].phase == "definition"
        nested = a.effects.by_scope[byname["caller.nested"]]
        assert sum(e.kind == "await" for e in nested) == 1
        lambda_scope = next(i for i, n in a.nodes.items() if n["node_type"] == "lambda")
        assert sum(e.kind == "call" for e in a.effects.by_scope[lambda_scope]) == 1
    finally:
        a.close()


@pytest.mark.parametrize(
    "operation",
    [
        "obj.change()",
        "async def nested():\n  await obj.change()",
        "callback=lambda: obj.change()",
        "other=C()\n await other.change()",
    ],
)
def test_deferred_or_independent_operations_do_not_poison_instance(tmp_path, operation):
    check(
        analyze(tmp_path, {"demo.py": source("receiver.run=b", operation, True)}, closed=False),
        "obj.run",
        {"a"},
        {"b"},
    )


@pytest.mark.parametrize("handler", ["absent", "unknown"])
def test_effect_handler_negative_control_reaches_final_calls(tmp_path, monkeypatch, handler):
    original = Analyzer.field_event

    def patched(self, event, receiver, name, receiver_name=None):
        if event.kind == "call" and ast.unparse(event.node.func) == "obj.change" and name == "run":
            return (
                None
                if handler == "absent"
                else EffectOutcome(EffectKind.UNKNOWN_EFFECT, "test-unknown-effect")
            )
        return original(self, event, receiver, name, receiver_name)

    monkeypatch.setattr(Analyzer, "field_event", patched)
    r = analyze(tmp_path, {"demo.py": source("pass")}, closed=False)
    s = check(r, "obj.run", {"a"}, {"b"}, True)
    expected = "missing-effect-handler" if handler == "absent" else "test-unknown-effect"
    assert expected in s["unresolved_reasons"]
    cov = s["resolution_decision"]["write_source_coverage"]
    assert not cov["complete"] and any(c["outcome"] == "UNKNOWN_EFFECT" for c in cov["checks"])
    # Jedi agrees about a in this control; agreement is not coverage.
    assert s["resolution_decision"]["jedi_targets"] == s["targets"]


def test_required_unhandled_event_is_not_coverage():
    node = ast.parse("await obj.change()").body[0].value
    event = EffectEvent("scope", node, "unhandled", 1, False, True, True, "body")
    cov = EffectCoverage("a-rule-label")
    cov.source("known-value", True)
    cov.require(event)
    assert not cov.export()["complete"]
    assert cov.export()["checks"][0]["outcome"] == "UNHANDLED"
    cov.record(event, EffectOutcome(EffectKind.UNKNOWN_EFFECT, "unsupported"))
    assert not cov.export()["complete"]
    cov.record(event, EffectOutcome(EffectKind.NO_EFFECT, "proved-independent-instance"))
    assert not cov.export()["complete"]
    independent = EffectCoverage("fresh-object-obligation")
    independent.source("known-value", True)
    independent.record(event, EffectOutcome(EffectKind.NO_EFFECT, "proved-independent-instance"))
    assert independent.export()["complete"]


@pytest.mark.parametrize("label", ["literal-slot-state", "python-instance-field-precedence"])
def test_rule_label_without_coverage_cannot_certify_even_matching_signals(tmp_path, label):
    a = analyzer_for(tmp_path, "def a(): pass\ndef caller(): a()\n")
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        target = next(i for i, n in a.nodes.items() if n["qualname"] == "a")
        expr = a.trees[scope].body[0].value.func
        value = certified(known("callable", target), label)
        result, decision = a.adjudicate(scope, expr, value, value)
        assert result.unknown and not a.complete(result)
        assert "missing-write-source-coverage" in result.reasons
        assert not decision["excluded_jedi_targets"]
    finally:
        a.close()


@pytest.mark.parametrize("through_alias", [False, True])
def test_unresolved_coverage_survives_field_alias(tmp_path, monkeypatch, through_alias):
    original = Analyzer.instance_field

    def patched(self, receiver, name, scope, anchor):
        result = original(self, receiver, name, scope, anchor)
        if name == "run":
            self.coverage[(scope, id(anchor))]["complete"] = False
            self.coverage[(scope, id(anchor))]["gaps"].append("test-unhandled-dependency")
        return result

    monkeypatch.setattr(Analyzer, "instance_field", patched)
    text = source("pass", "pass")
    if through_alias:
        text = text.replace(" obj.run()", " callback=obj.run\n callback()")
    expression = "callback" if through_alias else "obj.run"
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), expression, {"a"}, {"b"}, True)
    assert "missing-write-source-coverage" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["write_source_coverage"]["complete"]


@pytest.mark.parametrize(
    "mutation", ["obj.run: object=b", "obj.run += b", "del obj.run", "obj.run=b"]
)
def test_collector_covers_all_store_kinds(tmp_path, mutation):
    a = analyzer_for(tmp_path, source("pass", mutation))
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        writes = [e for e in a.effects.by_scope[scope] if e.kind == "write"]
        assert any(ast.unparse(e.node) == ast.unparse(ast.parse(mutation).body[0]) for e in writes)
    finally:
        a.close()


def test_precise_dictionary_copy_and_alias_remain_complete(tmp_path):
    text = """def a(): pass
def b(): pass
def caller():
 original={"go":a}
 copied={**original}
 original["go"]=b
 callback=copied["go"]
 callback()
"""
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "callback", {"a"}, {"b"})
    assert s["resolution_decision"]["write_source_coverage"]["complete"]


def test_slot_coverage_gap_survives_alias_and_jedi_agreement(tmp_path, monkeypatch):
    original = Analyzer.subscript

    def patched(self, scope, expr):
        result = original(self, scope, expr)
        self.coverage[(scope, id(expr))]["complete"] = False
        self.coverage[(scope, id(expr))]["gaps"].append("test-unhandled-slot-region")
        return result

    monkeypatch.setattr(Analyzer, "subscript", patched)
    text = "def a(): pass\ndef caller():\n table={'go':a}\n callback=table['go']\n callback()\n"
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "callback", {"a"}, set(), True)
    assert not s["resolution_decision"]["write_source_coverage"]["complete"]


def test_coverage_unknown_is_not_erased_by_another_dependency_visit():
    node = ast.parse("obj.change()").body[0].value
    event = EffectEvent("scope", node, "call", 1, False, True, True, "body")
    cov = EffectCoverage("shared-source-and-copy")
    cov.source("literal", True)
    cov.record(event, EffectOutcome(EffectKind.UNKNOWN_EFFECT, "source-escape"))
    cov.record(event, EffectOutcome(EffectKind.NO_EFFECT, "not-the-copy-object"))
    assert not cov.export()["complete"]
    assert cov.export()["checks"][0]["reason"] == "source-escape"


def test_call_argument_effects_run_even_when_outer_call_only_creates_coroutine(tmp_path):
    text = source("receiver.run=b", "obj.delayed(obj.change())")
    text = text.replace(
        "async def caller", " async def delayed(receiver,value): pass\nasync def caller"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"b"}, {"a"})


def test_unrelated_nested_body_in_region_does_not_resume(tmp_path):
    text = source(
        "receiver.run=b", "for _ in ():\n  async def nested():\n   await obj.change()", True
    )
    result = analyze(tmp_path, {"demo.py": text}, closed=False)
    s = check(result, "obj.run", {"a"}, {"b"}, True)
    assert "unsupported-protocol-region" in s["unresolved_reasons"]
    assert not any("deferred-" in r for r in s["unresolved_reasons"])
    owners = {n["node_id"]: n["qualname"] for n in result[0]}
    assert {
        owners[t["execution_owner"]] for t in result[2]["sites"] if t["expression"] == "obj.change"
    } == {"caller.nested"}


@pytest.mark.parametrize(
    "body",
    [
        "for receiver in (): pass\n  receiver.run=b",
        "with other as receiver: pass\n  receiver.run=b",
        "def receiver(): pass\n  receiver.run=b",
        "import other as receiver\n  receiver.run=b",
        "receiver += other\n  receiver.run=b",
    ],
)
def test_other_receiver_binding_syntax_refuses_summary(tmp_path, body):
    s = check(
        analyze(tmp_path, {"demo.py": source(body)}, closed=False), "obj.run", {"a"}, {"b"}, True
    )
    assert "receiver-binding-changed" in s["unresolved_reasons"]


@pytest.mark.parametrize(
    "operation",
    [
        "value=obj.change()",
        "if obj.change(): pass",
        "consume(obj.change())",
        "value=(obj.change(),)",
    ],
)
def test_nested_synchronous_calls_have_ordered_effects(tmp_path, operation):
    check(
        analyze(tmp_path, {"demo.py": source("receiver.run=b", operation)}, closed=False),
        "obj.run",
        {"b"},
        {"a"},
    )


def test_short_circuit_synchronous_effect_is_conditional(tmp_path):
    s = check(
        analyze(
            tmp_path,
            {"demo.py": source("receiver.run=b", "value=flag and obj.change()")},
            closed=False,
        ),
        "obj.run",
        {"a", "b"},
        set(),
        True,
    )
    cov = s["resolution_decision"]["write_source_coverage"]
    assert any(c["conditional"] and c["outcome"] == "UNKNOWN_EFFECT" for c in cov["checks"])


def test_unresolved_deferred_receiver_is_an_association_gap(tmp_path):
    s = check(
        analyze(tmp_path, {"demo.py": source("receiver.run=b", "await flag")}, closed=False),
        "obj.run",
        set(),
        {"a", "b"},
        True,
    )
    assert "deferred-receiver-association-gap" in s["unresolved_reasons"]


def test_arguments_are_evaluated_before_later_attribute_lookup(tmp_path):
    text = source("receiver.run=b", "consume(obj.change(),obj.run)")
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"b"}, {"a"})


@pytest.mark.parametrize(
    "receipt",
    [
        {"rule": "literal-slot-state", "events": [], "complete": True},
        {
            "required_events": ["missing"],
            "checks": [],
            "sources": [{"supported": True}],
            "complete": True,
        },
        {
            "required_events": ["x"],
            "checks": [{"event_id": "x", "outcome": "UNKNOWN_EFFECT"}],
            "sources": [{"supported": True}],
            "complete": True,
        },
    ],
)
def test_forged_complete_flag_cannot_exclude_jedi_or_certify(tmp_path, receipt):
    a = analyzer_for(tmp_path, "def a(): pass\ndef caller(): a()\n")
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        target = next(i for i, n in a.nodes.items() if n["qualname"] == "a")
        expr = a.trees[scope].body[0].value.func
        key = (scope, id(expr))
        a.coverage[key] = receipt
        value = certified(known("callable", target), "literal-slot-state")
        from lct.python_analysis import Result

        value = Result(value.atoms, value.reasons, value.proofs, frozenset([key]))
        result, decision = a.adjudicate(scope, expr, value, value)
        assert result.unknown and not a.complete(result)
        assert not decision["excluded_jedi_targets"]
    finally:
        a.close()


@pytest.mark.parametrize(
    "body",
    [
        "local=a\n  local += b\n  receiver.run=local",
        "local=a\n  local,unused=(b,a)\n  receiver.run=local",
    ],
)
def test_unsupported_dependent_local_binding_refuses_summary(tmp_path, body):
    s = check(
        analyze(tmp_path, {"demo.py": source(body)}, closed=False), "obj.run", {"a"}, {"b"}, True
    )
    assert "unsupported-summary-binding" in s["unresolved_reasons"]


@pytest.mark.parametrize(
    "operation",
    [
        "value=0 > 1 > await obj.change()",
        "value=flag < 1 < await obj.change()",
    ],
)
def test_chained_comparison_resumption_is_conditional(tmp_path, operation):
    text = source("receiver.run=b", operation, True)
    s = check(
        analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", set(), {"a", "b"}, True
    )
    assert "deferred-method-resumption-not-modeled" in s["unresolved_reasons"]
    a = analyzer_for(tmp_path, text)
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        assert next(e for e in a.effects.by_scope[scope] if e.kind == "await").conditional
    finally:
        a.close()


def test_executed_class_body_is_an_explicit_scope_dependency(tmp_path):
    text = source("receiver.run=b", "class Nested:\n  obj.run=b")
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "unsupported-class-definition-effects" in s["unresolved_reasons"]


def test_uninvoked_class_method_body_is_not_an_executed_class_dependency(tmp_path):
    text = source("receiver.run=b", "class Nested:\n  def change(): obj.run=b")
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})
