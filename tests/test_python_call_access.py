"""Open-input call-access contracts, independent of guessed side effects."""

import ast

import pytest

from lct.python_access import AccessKind
from lct.python_analysis import Analyzer
from lct.python_effects import (
    EffectCoverage,
    EffectEvent,
    EffectKind,
    EffectOutcome,
    valid_coverage,
)
from tests.test_python_effect_coverage import analyzer_for
from tests.test_python_pipeline import analyze, site
from tests.test_python_review_round3 import check

HEADER = """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
"""


@pytest.mark.parametrize("case", ["closure", "nested_argument"])
def test_review_counterexamples(tmp_path, case):
    if case == "closure":
        text = (
            HEADER
            + """def caller():
 obj=C()
 def mutate(): obj.run=b
 mutate()
 obj.run()
"""
        )
    else:
        text = (
            HEADER
            + """def caller(consume):
 obj=C()
 consume([obj])
 obj.run()
"""
        )
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


def test_uncalled_closure_is_not_executed(tmp_path):
    text = (
        HEADER
        + """def caller():
 obj=C()
 def mutate(): obj.run=b
 obj.run()
"""
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})


WRAPPERS = [
    ("consume(obj)", AccessKind.REACHABLE),
    ("consume([obj])", AccessKind.REACHABLE),
    ("consume((obj,))", AccessKind.REACHABLE),
    ("consume({'value':obj})", AccessKind.REACHABLE),
    ("consume({obj:1})", AccessKind.REACHABLE),
    ("consume([{'value':(obj,)}])", AccessKind.REACHABLE),
    ("payload=[{'value':obj}]\n consume(payload)", AccessKind.REACHABLE),
    ("consume(value=[obj])", AccessKind.REACHABLE),
    ("consume(*[obj])", AccessKind.REACHABLE),
    ("payload=(obj,)\n consume(*payload)", AccessKind.REACHABLE),
    ("consume(**{'value':obj})", AccessKind.REACHABLE),
    ("payload={'value':obj}\n consume(**payload)", AccessKind.REACHABLE),
    ("consume(source)", AccessKind.UNKNOWN),
    ("consume([source])", AccessKind.UNKNOWN),
    ("consume(**source)", AccessKind.UNKNOWN),
    ("consume(**{obj:1})", AccessKind.UNKNOWN),
    ("consume(*{'value':obj})", AccessKind.NOT_REACHABLE),
    ("consume(**{'value':1})", AccessKind.NOT_REACHABLE),
]


def inspect_call(tmp_path, text):
    a = analyzer_for(tmp_path, text)
    scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
    tree = a.trees[scope]
    receiver = next(
        v for v in a.resolve(scope, tree.body[-1].value.func.value).atoms if v.kind == "instance"
    )
    event = next(
        e
        for e in a.effects.by_scope[scope]
        if e.kind == "call" and isinstance(e.node.func, ast.Name) and e.node.func.id == "consume"
    )
    return a, scope, receiver, event


@pytest.mark.parametrize("operation,state", WRAPPERS)
def test_argument_transport_matrix(tmp_path, operation, state):
    text = HEADER + f"def caller(consume,source):\n obj=C()\n {operation}\n obj.run()\n"
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        args = [(x, "value") for x in event.node.args] + [
            (k.value, "kwargs" if k.arg is None else "value") for k in event.node.keywords
        ]
        results = [a.access.reachable(scope, x, receiver, event.node, mode=m) for x, m in args]
        assert results[0].state == state
        effect = a.field_event(event, receiver, "run")
        assert effect.kind == (
            EffectKind.NO_EFFECT if state == AccessKind.NOT_REACHABLE else EffectKind.UNKNOWN_EFFECT
        )
        assert effect.detail["call_access"]["entries"]
    finally:
        a.close()
    uncertain = state != AccessKind.NOT_REACHABLE
    s = check(
        analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, uncertain
    )
    assert not s["resolution_decision"]["excluded_jedi_targets"]


@pytest.mark.parametrize(
    "updates",
    [
        "payload[0]=obj",
        "payload[0]:object=obj",
        "payload.append(obj)",
        "modify(payload)",
        "payload[0]=payload",
    ],
)
def test_container_state_not_stale_literal(tmp_path, updates):
    text = (
        HEADER
        + f"def caller(consume,modify):\n obj=C()\n payload=[1]\n {updates}\n consume(payload)\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state != AccessKind.NOT_REACHABLE
        if "obj" in updates and "append" not in updates:
            assert result.state == AccessKind.REACHABLE
    finally:
        a.close()
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


@pytest.mark.parametrize(
    "body,setup,uncertain",
    [
        ("obj.run=b", "", True),
        ("other.run=b", "other=C()", False),
        ("obj=C()\n  obj.run=b", "", False),
        ("def nested(): obj.run=b", "", False),
        ("source.run=b", "", True),
        ("relay()", "def relay(): obj.run=b", True),
        ("relay()", "def relay(): pass", False),
        ("consume()", "", True),
        ("mutate()", "", True),
        ("return\n  obj.run=b", "", False),
    ],
)
def test_closure_scope_and_transitive_dependencies(tmp_path, body, setup, uncertain):
    text = (
        HEADER
        + f"def caller(consume,source):\n obj=C()\n {setup}\n def mutate():\n  {body}\n mutate()\n obj.run()\n"
    )
    s = check(
        analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, uncertain
    )
    if uncertain:
        assert not s["resolution_decision"]["excluded_jedi_targets"]


@pytest.mark.parametrize(
    "signature,body,uncertain",
    [
        ("cb=obj", "cb.run=b", True),
        ("cb=obj", "pass", False),
    ],
)
def test_default_parameter_entry_used_at_call_stage(tmp_path, signature, body, uncertain):
    text = (
        HEADER
        + f"def caller():\n obj=C()\n def mutate({signature}): {body}\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, uncertain)


def test_closure_binding_uses_invocation_not_future_assignment(tmp_path):
    text = (
        HEADER
        + """def caller():
 obj=C()
 original=obj
 def mutate(): obj.run=b
 mutate()
 obj=C()
 original.run()
"""
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "original.run", {"a"}, {"b"}, True)


def test_module_external_binding_is_a_dependency(tmp_path):
    text = (
        HEADER
        + """obj=C()
def mutate(): obj.run=b
def caller():
 mutate()
 obj.run()
"""
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_unknown_global_call_target_cannot_be_no_effect(tmp_path):
    text = (
        HEADER
        + """obj=C()
def caller(consume):
 consume()
 obj.run()
"""
    )
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "unresolved-call-target-access" in s["unresolved_reasons"]


@pytest.mark.parametrize("operation", ["consume(obj)", "consume([1])"])
def test_access_budget_never_proves_unreachable(tmp_path, operation):
    text = HEADER + f"def caller(consume):\n obj=C()\n {operation}\n obj.run()\n"
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        a.access.budget = 0
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state == AccessKind.UNKNOWN and "analysis-budget" in result.gaps
        assert a.field_event(event, receiver, "run").kind == EffectKind.UNKNOWN_EFFECT
    finally:
        a.close()


@pytest.mark.parametrize(
    "call", ["noop()", "noop(obj)", "other.change()", "obj.change()", "obj.delayed()"]
)
def test_known_effect_and_no_effect_precision(tmp_path, call):
    text = (
        HEADER
        + """def noop(value=None): pass
"""
        + f"""C_unused=1
class D(C):
 def change(self): self.run=b
 async def delayed(self): self.run=b
def caller():
 obj=D()
 other=D()
 {call}
 obj.run()
"""
    )
    expected = {"b"} if call == "obj.change()" else {"a"}
    check(
        analyze(tmp_path, {"demo.py": text}, closed=False),
        "obj.run",
        expected,
        {"a", "b"} - expected,
    )


BAD_PROOFS = [
    {},
    {
        "no_effect_basis": "all-inputs-disproved",
        "call_access": {"target_state": "UNKNOWN", "targets": [], "entries": []},
    },
    {
        "no_effect_basis": "all-inputs-disproved",
        "call_access": {
            "target_state": "RESOLVED",
            "targets": ["fn"],
            "definitions": [{"target": "fn", "version_id": "synthetic-version"}],
            "entries": [
                {
                    "state": "UNKNOWN",
                    "gaps": ["unresolved-origin"],
                    "evidence": [{"reason": "unresolved-origin"}],
                }
            ],
        },
    },
    {
        "no_effect_basis": "all-inputs-disproved",
        "call_access": {
            "target_state": "RESOLVED",
            "targets": ["fn"],
            "definitions": [{"target": "fn", "version_id": "synthetic-version"}],
            "entries": [
                {"state": "REACHABLE", "gaps": [], "evidence": [{"reason": "closure-binding"}]}
            ],
        },
    },
]


@pytest.mark.parametrize("detail", BAD_PROOFS)
def test_no_effect_label_without_access_proof_is_rejected(detail):
    node = ast.parse("mutate()").body[0].value
    event = EffectEvent("scope", node, "call", 1, False, True, True, "body")
    cov = EffectCoverage("instance-field-coverage")
    cov.source("captured-instance", True)
    cov.record(event, EffectOutcome(EffectKind.NO_EFFECT, "a-label", detail=detail))
    receipt = cov.export()
    assert not receipt["complete"]
    receipt["complete"] = True
    assert not valid_coverage(receipt)


@pytest.mark.parametrize("detail", BAD_PROOFS)
def test_invalid_no_effect_proof_cannot_bypass_matching_jedi(tmp_path, monkeypatch, detail):
    original = Analyzer.call_field_effect

    def forged(self, event, receiver, name, receiver_name=None):
        if isinstance(event.node.func, ast.Name) and event.node.func.id == "mutate":
            return EffectOutcome(EffectKind.NO_EFFECT, "a-label", detail=detail)
        return original(self, event, receiver, name, receiver_name)

    monkeypatch.setattr(Analyzer, "call_field_effect", forged)
    text = HEADER + "def caller():\n obj=C()\n def mutate(): pass\n mutate()\n obj.run()\n"
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    decision = s["resolution_decision"]
    assert decision["jedi_targets"] == s["targets"]
    assert not decision["write_source_coverage"]["complete"]
    assert not decision["excluded_jedi_targets"]


def test_transitive_analysis_budget_is_explicit(tmp_path):
    text = HEADER + "def caller():\n obj=C()\n def mutate(): pass\n mutate()\n obj.run()\n"
    a = analyzer_for(tmp_path, text)
    try:
        scope = next(i for i, n in a.nodes.items() if n["qualname"] == "caller")
        expr = a.trees[scope].body[-1].value.func.value
        receiver = next(v for v in a.resolve(scope, expr).atoms if v.kind == "instance")
        event = next(
            e
            for e in a.effects.by_scope[scope]
            if e.kind == "call" and ast.unparse(e.node.func) == "mutate"
        )
        a.access.budget = 0
        effect = a.field_event(event, receiver, "run")
        assert effect.kind == EffectKind.UNKNOWN_EFFECT
        assert "analysis-budget" in effect.reason
        assert a.limited
    finally:
        a.close()


def test_finite_summary_is_snapshot_local_and_reused(tmp_path):
    text = (
        HEADER
        + "def caller():\n obj=C()\n def mutate():\n  def nested(): obj.run=b\n  return\n  obj.run=b\n obj.run()\n"
    )
    a = analyzer_for(tmp_path, text)
    try:
        ident = next(i for i, n in a.nodes.items() if n["qualname"] == "caller.mutate")
        first = a.access.summary(ident)
        assert a.access.summary(ident) is first
        assert first["version_id"] == a.nodes[ident]["version_id"]
        assert not first["captures"] and not first["calls"]
    finally:
        a.close()


def test_known_parameter_binding_is_not_a_capture(tmp_path):
    text = (
        HEADER
        + "def caller():\n obj=C()\n other=C()\n def mutate(obj): obj.run=b\n mutate(other)\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})


def test_nonlocal_binding_is_captured(tmp_path):
    text = (
        HEADER
        + "def caller():\n obj=C()\n def mutate():\n  nonlocal obj\n  obj.run=b\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_independent_object_with_known_receiver_reference_is_not_independent(tmp_path):
    text = (
        HEADER
        + "def caller():\n obj=C()\n other=C()\n other.ref=obj\n def mutate(): other.run=b\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_callable_argument_can_expose_capture(tmp_path):
    text = (
        HEADER
        + "def caller(consume):\n obj=C()\n def mutate(): obj.run=b\n consume(mutate)\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


@pytest.mark.parametrize("modifier,body", [("async ", "obj.run=b"), ("", "obj.run=b\n  yield 1")])
def test_delayed_closure_creation_does_not_execute_dependencies(tmp_path, modifier, body):
    text = (
        HEADER
        + f"def caller():\n obj=C()\n {modifier}def mutate():\n  {body}\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})


def test_constructor_dependency_of_transitive_call_is_not_skipped(tmp_path):
    text = (
        HEADER
        + "def caller():\n obj=C()\n class Wrapper:\n  def __init__(self): obj.run=b\n def mutate(): Wrapper()\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_prior_escape_disables_private_input_proof(tmp_path):
    text = HEADER + "def caller(consume,saved):\n obj=C()\n saved[0]=obj\n consume()\n obj.run()\n"
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "unresolved-call-target-access" in s["unresolved_reasons"]


@pytest.mark.parametrize("binding", ["obj", "alias"])
def test_late_captured_binding_cannot_support_private_proof(tmp_path, binding):
    assignment = "" if binding == "obj" else "alias=obj"
    text = (
        HEADER
        + f"def caller(consume,publish):\n def exposed(): return {binding}\n publish(exposed)\n obj=C()\n {assignment}\n consume()\n obj.run()\n"
    )
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "unresolved-call-target-access" in s["unresolved_reasons"]


def test_object_argument_includes_class_method_capture(tmp_path):
    text = """def a(): pass
def b(): pass
def caller(consume):
 class C:
  def __init__(self): self.run=a
  def reach(self): obj.run=b
 obj=C()
 other=C()
 consume(other)
 obj.run()
"""
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_only_rule_label_is_not_an_access_source(tmp_path):
    from lct.python_analysis import Result, certified

    text = HEADER + "def caller(consume):\n obj=C()\n consume(obj)\n obj.run()\n"
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        r = a.access.values(certified(Result(), "literal-slot-state"), scope, receiver, event.node)
        assert r.state == AccessKind.UNKNOWN
    finally:
        a.close()


def test_factory_local_object_update_is_not_disproved_from_inputs(tmp_path):
    text = (
        HEADER
        + "def factory():\n local=C()\n local.run=b\n return local\ndef caller():\n factory().run()\n"
    )
    r = analyze(tmp_path, {"demo.py": text}, closed=False)
    s = site(r, "factory().run", "caller")
    assert s["unknown_origin"] and not s["complete"]
    assert "local-allocation-effects-not-modeled" in " ".join(s["unresolved_reasons"])
    assert not s["resolution_decision"]["excluded_jedi_targets"]


@pytest.mark.parametrize(
    "prefix,value,state",
    [
        ("*", "obj", AccessKind.NOT_REACHABLE),
        ("*", "1", AccessKind.NOT_REACHABLE),
        ("**", "obj", AccessKind.REACHABLE),
        ("**", "1", AccessKind.NOT_REACHABLE),
    ],
)
def test_known_dictionary_expansion_uses_actual_argument_semantics(tmp_path, prefix, value, state):
    text = (
        HEADER
        + f"def caller(consume):\n obj=C()\n payload={{'key':{value}}}\n consume({prefix}{{**payload}})\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        expr = event.node.args[0] if prefix == "*" else event.node.keywords[0].value
        result = a.access.reachable(
            scope, expr, receiver, event.node, mode="value" if prefix == "*" else "kwargs"
        )
        assert result.state == state
    finally:
        a.close()
    check(
        analyze(tmp_path, {"demo.py": text}, closed=False),
        "obj.run",
        {"a"},
        {"b"},
        state != AccessKind.NOT_REACHABLE,
    )


def test_container_changed_via_capture_is_not_certified_from_creation_literal(tmp_path):
    text = (
        HEADER
        + "def caller(consume):\n obj=C()\n payload=[]\n def mutate(): payload.append(obj)\n mutate()\n consume(payload)\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state != AccessKind.NOT_REACHABLE
        assert "captured-container-mutation-not-modeled" in result.gaps
    finally:
        a.close()
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


@pytest.mark.parametrize("declaration", ["global obj", "if True:\n   global obj"])
def test_global_declaration_does_not_capture_same_named_outer_local(tmp_path, declaration):
    text = (
        HEADER
        + f"obj=C()\ndef caller():\n obj=C()\n def mutate():\n  {declaration}\n  obj.run=b\n mutate()\n obj.run()\n"
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})


@pytest.mark.parametrize(
    "expression,state",
    [
        ("(lambda:obj)()", AccessKind.REACHABLE),
        ("(lambda:1)()", AccessKind.NOT_REACHABLE),
        ("(lambda value:value)(obj)", AccessKind.REACHABLE),
        ("(lambda value:1)(obj)", AccessKind.NOT_REACHABLE),
    ],
)
def test_call_argument_lambda_returns_have_safe_value_guards(tmp_path, expression, state):
    text = HEADER + f"def caller(consume):\n obj=C()\n consume({expression})\n obj.run()\n"
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state == state
    finally:
        a.close()
    r = analyze(tmp_path, {"demo.py": text}, closed=False)
    s = site(r, "obj.run", "caller")
    assert s["names"] == {"a"} and "b" not in s["names"]
    assert s["unknown_origin"] is (state == AccessKind.REACHABLE)
    assert s["complete"] is (state == AccessKind.NOT_REACHABLE)


@pytest.mark.parametrize("updates", ["alias=payload", "alias=payload\n alias[0]=obj"])
def test_multiple_container_aliases_use_shared_current_slots(tmp_path, updates):
    initial = "obj" if updates == "alias=payload" else "1"
    text = (
        HEADER
        + f"def caller(consume):\n obj=C()\n payload=[{initial}]\n {updates}\n consume(alias)\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state == AccessKind.REACHABLE
    finally:
        a.close()
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_transitive_container_mutation_is_not_a_negative_access_proof(tmp_path):
    text = (
        HEADER
        + "def caller(consume):\n obj=C()\n payload=[]\n def fill(): payload.append(obj)\n def relay(): fill()\n relay()\n consume(payload)\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state != AccessKind.NOT_REACHABLE
    finally:
        a.close()
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)


def test_independent_object_modified_by_capture_has_unknown_access(tmp_path):
    text = (
        HEADER
        + "def caller(consume):\n obj=C()\n other=C()\n def attach(): other.ref=obj\n attach()\n consume(other)\n obj.run()\n"
    )
    a, scope, receiver, event = inspect_call(tmp_path, text)
    try:
        result = a.access.reachable(scope, event.node.args[0], receiver, event.node)
        assert result.state != AccessKind.NOT_REACHABLE
    finally:
        a.close()
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
