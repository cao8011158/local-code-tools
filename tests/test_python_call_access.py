"""Call argument and receiver scenarios use Jedi signatures as target authority."""

import jedi
import pytest

from tests.test_python_pipeline import analyze, site


CASES = [
    ("direct callback", "def a(): pass\ndef execute(cb): cb()\ndef run(): execute(a)\n", "cb", "execute", {"a"}),
    ("default callback", "def a(): pass\ndef execute(cb=a): cb()\ndef run(): execute()\n", "cb", "execute", {"a"}),
    ("keyword callback", "def a(): pass\ndef execute(cb): cb()\ndef run(): execute(cb=a)\n", "cb", "execute", {"a"}),
    ("returned callable", "def a(): pass\ndef factory(): return a\ndef run(): factory()()\n", "factory()", "run", {"a"}),
    ("literal container", "def a(): pass\ndef run():\n table={'go':a}\n table['go']()\n", "table['go']", "run", {"a"}),
    ("unknown parameter", "def run(callback): callback()\n", "callback", "run", set()),
    ("unknown attribute", "def run(obj): obj.handler()\n", "obj.handler", "run", set()),
]


@pytest.mark.parametrize("label,source,expression,owner,expected", CASES, ids=[c[0] for c in CASES])
def test_call_site_consumes_explicit_jedi_contract(tmp_path, label, source, expression, owner, expected):
    result = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = site(result, expression, owner)
    assert observed["names"] == expected, label
    assert observed["target_provider"] == "jedi-get-signatures"
    assert observed["evidence"][1]["api"] == "get_signatures"
    assert observed["evidence"][1]["position"]
    if not expected:
        assert observed["unknown_origin"] and "jedi-no-result" in observed["unresolved_reasons"]
    else:
        assert not observed["unknown_origin"]


def test_utf8_call_parenthesis_uses_jedi_character_position(tmp_path):
    source = "def café(): pass\ndef run():\n café(\n )\n"
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = site(graph, "café", "run")
    assert observed["names"] == {"café"}
    assert observed["evidence"][1]["api"] == "get_signatures"
    line, column = observed["evidence"][1]["position"]
    assert (line, column) == (3, 6)  # Jedi receives character column just after '('
    assert {n.name for n in jedi.Script(source).get_signatures(line, column)} == {"café"}


def test_same_named_unknown_receiver_does_not_conjure_method(tmp_path):
    source = "class C:\n def handler(self): pass\ndef run(obj): obj.handler()\n"
    observed = site(analyze(tmp_path, {"demo.py": source}, closed=False), "obj.handler", "run")
    assert observed["names"] == set()
    assert observed["unknown_origin"]
    assert not observed["complete"]


HEADER = "def a(): pass\ndef b(): pass\nclass C:\n def __init__(self): self.run=a\n"

# The historical access-state matrix remains as captured source scenarios.
# Jedi 0.20.1's direct get_signatures probe of obj.run's opening parenthesis
# returns a for these concrete snippets; no LCT receiver-effect proof is used.
WRAPPERS = [
    "consume(obj)", "consume([obj])", "consume((obj,))",
    "consume({'value':obj})", "consume({obj:1})",
    "consume([{'value':(obj,)}])", "payload=[{'value':obj}]\n consume(payload)",
    "consume(value=[obj])", "consume(*[obj])", "payload=(obj,)\n consume(*payload)",
    "consume(**{'value':obj})", "payload={'value':obj}\n consume(**payload)",
    "consume(source)", "consume([source])", "consume(**source)",
    "consume(**{obj:1})", "consume(*{'value':obj})", "consume(**{'value':1})",
]


@pytest.mark.parametrize("operation", WRAPPERS)
def test_argument_transport_keeps_jedi_observation_and_field_source(tmp_path, operation):
    source = HEADER + f"def caller(consume,source):\n obj=C()\n {operation}\n obj.run()\n"
    direct = jedi.Script(source).get_signatures(len(source.splitlines()), 9)
    assert {name.name for name in direct} == {"a"}
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = site(graph, "obj.run", "caller")
    assert observed["names"] == {"a"}
    assert observed["target_provider"] == "jedi-get-signatures"
    assert any(row["key"] == "string:run" for row in graph[2]["_unit_subscriptions"])


FIELD_OPERATIONS = [
    "payload[0]=obj", "payload[0]:object=obj", "payload.append(obj)",
    "modify(payload)", "payload[0]=payload",
]


@pytest.mark.parametrize("update", FIELD_OPERATIONS)
def test_mutated_argument_container_does_not_override_jedi_field_call(tmp_path, update):
    source = HEADER + f"def caller(consume,modify):\n obj=C()\n payload=[1]\n {update}\n consume(payload)\n obj.run()\n"
    assert {name.name for name in jedi.Script(source).get_signatures(len(source.splitlines()), 9)} == {"a"}
    observed = site(analyze(tmp_path, {"demo.py": source}, closed=False), "obj.run", "caller")
    assert observed["names"] == {"a"}
    assert observed["evidence"][1]["api"] == "get_signatures"


@pytest.mark.parametrize("operation", ("noop()", "noop(obj)", "other.change()", "obj.change()"))
def test_field_effect_syntax_keeps_raw_jedi_target(tmp_path, operation):
    source = HEADER + """def noop(value=None): pass
class D(C):
 def change(self): self.run=b
def caller():
 obj=D()
 other=D()
""" + f" {operation}\n obj.run()\n"
    # Jedi's signature describes the callable declaration; no execution-order
    # field mutation is inferred from LCT's former custom effect engine.
    expected = {"b"}
    assert {name.name for name in jedi.Script(source).get_signatures(len(source.splitlines()), 9)} == expected
    assert site(analyze(tmp_path, {"demo.py": source}, closed=False), "obj.run", "caller")["names"] == expected


CLOSURE_CASES = [
    ("same receiver", "obj.run=b", ""),
    ("independent receiver", "other.run=b", "other=C()"),
    ("rebound receiver", "obj=C()\n  obj.run=b", ""),
    ("uninvoked nested body", "def nested(): obj.run=b", ""),
    ("external receiver", "source.run=b", ""),
    ("transitive relay", "relay()", "def relay(): obj.run=b"),
    ("unknown call", "consume()", ""),
    ("unreachable store", "return\n  obj.run=b", ""),
    ("nonlocal binding", "nonlocal obj\n  obj.run=b", ""),
]


@pytest.mark.parametrize("label,body,setup", CLOSURE_CASES, ids=[x[0] for x in CLOSURE_CASES])
def test_closure_and_receiver_syntax_follows_raw_jedi(tmp_path, label, body, setup):
    source = (HEADER + f"def caller(consume,source):\n obj=C()\n {setup}\n"
              f" def mutate():\n  {body}\n mutate()\n obj.run()\n")
    expected = {"a"}  # Verified Jedi 0.20.1 signatures for each literal source above.
    assert {n.name for n in jedi.Script(source).get_signatures(len(source.splitlines()), 9)} == expected
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = site(graph, "obj.run", "caller")
    assert observed["names"] == expected
    assert observed["target_provider"] == "jedi-get-signatures"
    assert all("resolution_decision" not in s for s in graph[2]["sites"])
