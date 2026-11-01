"""Exact Jedi targets can use source-only lexical evidence for simple aliases."""

from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze, site


def test_alias_uses_jedi_target_with_same_source_evidence(tmp_path, monkeypatch):
    source = "def target(): pass\ndef caller():\n first=target\n second=first\n second()\n"
    fast = analyze(tmp_path, {"demo.py": source})
    selected = site(fast, "second", "caller")
    assert selected["names"] == {"target"}
    assert selected["resolution_decision"]["target_provider"] == "jedi-exact-captured-definition"
    assert fast[2]["tool_first_sites"] == 1
    assert fast[2]["source_only_lexical_visits"] == 3
    assert fast[2]["legacy_target_sites"] == 0

    monkeypatch.setattr(Analyzer, "tool_first_lexical", lambda *args: None)
    legacy = analyze(tmp_path, {"demo.py": source})
    old = site(legacy, "second", "caller")
    assert selected["evidence"][2]["association_trace"] == old["evidence"][2]["association_trace"]
    assert selected["targets"] == old["targets"]
    for key in ("_unit_supports", "_unit_subscriptions", "_unit_writes",
                "_unit_analysis_reads", "_analysis_reads", "_analysis_inputs"):
        assert fast[2][key] == legacy[2][key]


def test_parameter_shadow_and_unbound_keep_semantic_resolution(tmp_path):
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
    parameter = site(graph, "alias", "run")
    assert parameter["names"] == {"target"}
    assert parameter["resolution_decision"]["target_provider"] == "finite-association-with-jedi-signal"
    assert graph[2]["tool_first_sites"] == 2
    unbound = site(graph, "alias", "unbound")
    assert unbound["resolution_decision"]["target_provider"] == "jedi-exact-captured-definition"
    assert unbound["names"] == {"target"}


def test_registry_and_field_remain_legacy(tmp_path):
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
    assert site(graph, "R['go']", "caller")["names"] == {"target"}
    assert site(graph, "self.handler", "C.run")["names"] == {"target"}
    assert site(graph, "R['go']", "caller")["resolution_decision"]["target_provider"] == "finite-association-with-jedi-signal"
    assert site(graph, "self.handler", "C.run")["resolution_decision"]["target_provider"] == "finite-association-with-jedi-signal"
