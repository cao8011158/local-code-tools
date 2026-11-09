"""Implicit execution must not inherit an absence-of-direct-reference proof."""

import ast

import pytest

from lct.python_analysis import Analyzer
from lct.python_effects import (
    EffectCoverage,
    EffectEvent,
    EffectKind,
    EffectOutcome,
    valid_coverage,
)
from tests.test_python_pipeline import analyze
from tests.test_python_review_round3 import check

HEADER = """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
"""
DECORATOR = """def caller():
 obj=C()
 def decorate(fn):
  obj.run=b
  return fn
 @decorate
 def unused(): pass
 obj.run()
"""
MANAGER = """def caller():
 obj=C()
 class Manager:
  def __enter__(self): obj.run=b
  def __exit__(self,*args): pass
 with Manager(): pass
 obj.run()
"""


@pytest.mark.parametrize("body", [DECORATOR, MANAGER], ids=["decorator", "with-enter"])
def test_review_counterexamples(tmp_path, body):
    text = HEADER + body
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})
    assert s["line"] == len(text.splitlines()) and s["column"] == 1
    assert s["target_provider"] == "jedi-get-signatures"


@pytest.mark.parametrize(
    "body",
    [DECORATOR.replace(" @decorate\n", ""), MANAGER.replace(" with Manager(): pass\n", "")],
    ids=["function-only", "class-only"],
)
def test_unapplied_definitions_have_no_implicit_effect(tmp_path, body):
    s = check(analyze(tmp_path, {"demo.py": HEADER + body}, closed=False), "obj.run", {"a"}, {"b"})
    assert not s["unresolved_reasons"]


def receipt(node, kind, detail=None, reachable=True):
    event = EffectEvent("scope", node, kind, 1, False, True, reachable, "body")
    cov = EffectCoverage("instance-field-coverage")
    cov.source("captured-source", True)
    cov.record(event, EffectOutcome(EffectKind.NO_EFFECT, "label-only", detail=detail or {}))
    return cov.export()


@pytest.mark.parametrize(
    "kind,source",
    [
        ("implicit-call", "decorate"),
        ("region", "with manager: pass"),
        ("scope-execution", "class Empty: pass"),
    ],
)
def test_no_effect_label_is_not_execution_proof(kind, source):
    node = ast.parse(source).body[0]
    if isinstance(node, ast.Expr):
        node = node.value
    r = receipt(node, kind)
    assert not r["complete"]
    r["complete"] = True
    assert not valid_coverage(r)


@pytest.mark.parametrize(
    "kind,source",
    [
        ("implicit-call", "decorate"),
        ("region", "with manager: pass"),
        ("scope-execution", "class Empty: pass"),
    ],
)
@pytest.mark.parametrize(
    "detail",
    [
        {"proof": True, "supported": True},
        {"execution_evidence": True},
        {"reachable": False, "event_kind": "write", "syntax": "Pass"},
    ],
)
def test_flags_and_handler_metadata_cannot_certify_execution(kind, source, detail):
    node = ast.parse(source).body[0]
    if isinstance(node, ast.Expr):
        node = node.value
    r = receipt(node, kind, detail)
    assert not r["complete"]
    assert r["checks"][0]["reachable"] is True
    assert r["checks"][0]["event_kind"] == kind


@pytest.mark.parametrize(
    "kind,source",
    [
        ("implicit-call", "decorate"),
        ("region", "with manager: pass"),
        ("scope-execution", "class Empty: pass"),
    ],
)
def test_unreachable_execution_keeps_existing_rule(kind, source):
    node = ast.parse(source).body[0]
    if isinstance(node, ast.Expr):
        node = node.value
    assert receipt(node, kind, reachable=False)["complete"]


@pytest.mark.parametrize(
    "source",
    [
        "class Empty: pass",
        "class Manager:\n def __enter__(self): obj.run=b\n async def __aexit__(self,*args): await arbitrary()",
        "class Constants:\n 'doc'\n def method(self,value=1)->None: arbitrary()",
    ],
)
def test_inert_class_evidence_is_required_and_verified(source):
    from lct.python_effects import implicit_execution_effect

    node = ast.parse(source).body[0]
    event = EffectEvent("scope", node, "scope-execution", 1, False, False, True, "definition")
    effect = implicit_execution_effect(event)
    assert effect.kind == EffectKind.NO_EFFECT
    cov = EffectCoverage("instance-field-coverage")
    cov.source("capture", True)
    cov.record(event, effect)
    r = cov.export()
    assert valid_coverage(r)
    check = r["checks"][0]
    proof = check.pop("execution_evidence")
    assert not valid_coverage(r)
    check["execution_evidence"] = dict(proof, source="class Different: pass")
    assert not valid_coverage(r)
    check["execution_evidence"] = dict(proof, line=proof["line"] + 1)
    assert not valid_coverage(r)
    check["execution_evidence"] = dict(proof, column=proof["column"] + 1)
    assert not valid_coverage(r)
    check["execution_evidence"] = proof
    assert valid_coverage(r)


@pytest.mark.parametrize(
    "source",
    [
        "class Child(Base): pass",
        "class Child:\n value=1",
        "class Child:\n value:'int'=1",
        "class Child:\n def method(self,value:Type): pass",
        "class Child(metaclass=Meta): pass",
        "@decorate\nclass Child: pass",
        "class Child:\n def method(self,value=call()): pass",
        "class Child:\n @decorate\n def method(self): pass",
        "class Child:\n value=call()",
        "class Child:\n with manager: pass",
    ],
)
def test_unsupported_class_execution_is_unknown(source):
    from lct.python_effects import implicit_execution_effect

    node = ast.parse(source).body[0]
    effect = implicit_execution_effect(
        EffectEvent("scope", node, "scope-execution", 1, False, False, True, "definition")
    )
    assert effect.kind == EffectKind.UNKNOWN_EFFECT
    assert effect.reason == "unsupported-class-definition-effects"


@pytest.mark.parametrize(
    "operation,asynchronous",
    [
        ("with Manager(): pass", False),
        ("async with Manager(): pass", True),
    ],
)
def test_context_protocol_boundary_is_explicit(tmp_path, operation, asynchronous):
    body = MANAGER.replace("with Manager(): pass", operation)
    if asynchronous:
        body = body.replace("def caller():", "async def caller():")
    graph = analyze(tmp_path, {"demo.py": HEADER + body}, closed=False)
    s = check(graph, "obj.run", {"a"}, {"b"})
    assert s["target_provider"] == "jedi-get-signatures"
    assert any(e["kind"] == "CONTEXT_ENTERS" for e in graph[1])


@pytest.mark.parametrize(
    "kind,source",
    [
        ("implicit-call", "decorate"),
        ("region", "with manager: pass"),
        ("scope-execution", "class Empty: pass"),
    ],
)
def test_source_forms_keep_jedi_call_observation(tmp_path, kind, source):
    if kind == "implicit-call":
        body = DECORATOR.replace("  obj.run=b", "  pass")
    elif kind == "region":
        body = MANAGER.replace("def __enter__(self): obj.run=b", "def __enter__(self): pass")
    else:
        body = "def caller():\n obj=C()\n class Empty: pass\n obj.run()\n"
    graph = analyze(tmp_path, {"demo.py": HEADER + body}, closed=False)
    observed = check(graph, "obj.run", {"a"}, {"b"})
    assert observed["target_provider"] == "jedi-get-signatures"
    assert "resolution_decision" not in observed


def test_decorator_application_after_return_does_not_execute(tmp_path):
    body = DECORATOR.replace(" @decorate", " return\n @decorate")
    s = check(analyze(tmp_path, {"demo.py": HEADER + body}, closed=False), "obj.run", {"a"}, {"b"})
    assert not s["unresolved_reasons"]


@pytest.mark.parametrize(
    "kind,source",
    [
        ("implicit-call", "decorate"),
        ("region", "with manager: pass"),
        ("scope-execution", "class Empty: pass"),
    ],
)
def test_unsupported_known_effect_label_cannot_certify_execution(kind, source):
    node = ast.parse(source).body[0]
    if isinstance(node, ast.Expr):
        node = node.value
    event = EffectEvent("scope", node, kind, 1, False, True, True, "body")
    cov = EffectCoverage("instance-field-coverage")
    cov.source("capture", True)
    cov.record(
        event, EffectOutcome(EffectKind.KNOWN_EFFECT, "renamed-label", detail={"proof": True})
    )
    assert not cov.export()["complete"]
