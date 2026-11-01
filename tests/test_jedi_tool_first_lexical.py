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


def test_shared_alias_suffix_replays_source_inputs_for_each_consumer(tmp_path, monkeypatch):
    source = "def first(): pass\na0=first\na1=a0\ndef one(): a1()\ndef two(): a1()\n"
    selected = analyze(tmp_path, {"demo.py": source})
    assert selected[2]["tool_first_sites"] == 2
    assert selected[2]["source_only_lexical_visits"] == 4
    monkeypatch.setattr(Analyzer, "tool_first_lexical", lambda *args: None)
    legacy = analyze(tmp_path, {"demo.py": source})
    for owner in ("one", "two"):
        new_site, old_site = site(selected, "a1", owner), site(legacy, "a1", owner)
        assert new_site["targets"] == old_site["targets"]
        assert new_site["evidence"][2]["association_trace"] == old_site["evidence"][2]["association_trace"]
    for key in ("_unit_input_events", "_unit_supports", "_analysis_inputs", "_unit_analysis_reads"):
        assert selected[2][key] == legacy[2][key]


def test_shared_source_change_delete_and_unrelated_growth(tmp_path):
    prefix = "def first(): pass\ndef second(): pass\n"
    for noise_count in (0, 20, 100):
        noise = "".join(f"def noise_{i}():\n private={{}}\n private['x']={i}\n"
                        for i in range(noise_count))
        original = analyze(tmp_path, {"demo.py": prefix + "a0=first\na1=a0\ndef one(): a1()\ndef two(): a1()\n" + noise})
        changed = analyze(tmp_path, {"demo.py": prefix + "a0=second\na1=a0\ndef one(): a1()\ndef two(): a1()\n" + noise})
        deleted = analyze(tmp_path, {"demo.py": prefix + "a0=first\ndel a0\na1=a0\ndef one(): a1()\ndef two(): a1()\n" + noise})
        for owner in ("one", "two"):
            assert site(original, "a1", owner)["names"] == {"first"}
            assert site(changed, "a1", owner)["names"] == {"second"}
            assert site(deleted, "a1", owner)["names"] == set()
        assert original[2]["source_only_lexical_visits"] == 4
        assert changed[2]["source_only_lexical_visits"] == 4
        assert deleted[2]["tool_first_sites"] == 0
