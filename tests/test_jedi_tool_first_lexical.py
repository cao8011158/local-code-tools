"""Aliases and rebinding use Jedi observations with source-only dependencies."""

import jedi
import pytest

from tests.test_python_pipeline import analyze, site


def test_shared_alias_suffix_uses_jedi_for_both_consumers(tmp_path):
    source = "def first(): pass\na0=first\na1=a0\ndef one(): a1()\ndef two(): a1()\n"
    graph = analyze(tmp_path, {"demo.py": source})
    assert {n.name for n in jedi.Script(source).get_signatures(4, 14)} == {"first"}
    for owner in ("one", "two"):
        observed = site(graph, "a1", owner)
        assert observed["names"] == {"first"}
        assert observed["target_provider"] == "jedi-get-signatures"
    assert graph[2]["_unit_supports"]


def test_parameter_shadow_and_unbound_keep_distinct_observations(tmp_path):
    source = """def target(): pass
def run(target):
 alias=target
 alias()
def unbound():
 alias=target
 alias()
 alias=1
def driver(): run(target)
"""
    graph = analyze(tmp_path, {"demo.py": source})
    assert site(graph, "alias", "run")["names"] == {"target"}
    assert site(graph, "alias", "unbound")["names"] == {"target"}
    for s in graph[2]["sites"]:
        assert "resolution_decision" not in s


def test_registration_gap_and_instance_field_are_separate_jedi_results(tmp_path):
    source = """def target(): pass
R={}
def register(key, fn): R[key]=fn
register('go', target)
class C:
 def __init__(self): self.handler=target
 def run(self): self.handler()
def caller():
 R['go']()
 C().run()
"""
    graph = analyze(tmp_path, {"demo.py": source})
    registered = site(graph, "R['go']", "caller")
    assert registered["names"] == set()
    assert "jedi-no-result" in registered["unresolved_reasons"]
    assert site(graph, "self.handler", "C.run")["names"] == {"target"}
    assert graph[2]["_unit_subscriptions"]
    assert graph[2]["_unit_writes"]


@pytest.mark.parametrize("count", (0, 20, 100))
def test_alias_change_and_delete_with_unrelated_growth(tmp_path, count):
    prefix = "def first(): pass\ndef second(): pass\n"
    noise = "".join(f"def noise_{i}():\n private={{}}\n private['x']={i}\n"
                    for i in range(count))
    states = (("a0=first", {"first"}), ("a0=second", {"second"}),
              ("a0=first\ndel a0", set()))
    for assignment, expected in states:
        source = prefix + assignment + "\na1=a0\ndef one(): a1()\ndef two(): a1()\n" + noise
        graph = analyze(tmp_path, {"demo.py": source})
        for owner in ("one", "two"):
            observed = site(graph, "a1", owner)
            assert observed["names"] == expected
            if not expected:
                assert "jedi-no-result" in observed["unresolved_reasons"]
