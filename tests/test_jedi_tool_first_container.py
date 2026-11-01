"""Jedi selected literal slots retain source and dependency evidence."""

from lct.python_analysis import Analyzer
from lct.storage import build
from tests.test_python_pipeline import analyze, site
from tests.synthetic_support import forbid_provider, initialize


def test_private_literal_read_uses_jedi_without_slot_target_inference(tmp_path, monkeypatch):
    source = 'def target(): pass\ndef caller():\n table={"go":target}\n table["go"]()\n'
    original = Analyzer.container_slots
    calls = []

    def watched(self, *args, **kwargs):
        calls.append(args[0].target)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Analyzer, "container_slots", watched)
    selected = analyze(tmp_path, {"demo.py": source})
    new_site = site(selected, "table['go']", "caller")
    assert new_site["names"] == {"target"}
    assert new_site["resolution_decision"]["target_provider"] == "jedi-exact-captured-definition"
    assert new_site["resolution_decision"]["reason"] == "jedi-target-with-container-source"
    assert selected[2]["source_only_container_reads"] == 1
    assert not calls

    monkeypatch.setattr(Analyzer, "container_slots", original)
    monkeypatch.setattr(Analyzer, "tool_first_subscript", lambda *args: None)
    legacy = analyze(tmp_path, {"demo.py": source})
    old_site = site(legacy, "table['go']", "caller")
    for key in ("targets", "complete", "unknown_origin", "unresolved_reasons"):
        assert new_site[key] == old_site[key]
    assert new_site["evidence"][2]["association_trace"] == old_site["evidence"][2]["association_trace"]
    assert (new_site["resolution_decision"]["write_source_coverage"] ==
            old_site["resolution_decision"]["write_source_coverage"])
    for key in ("_unit_supports", "_unit_subscriptions", "_unit_writes",
                "_analysis_inputs", "_unit_input_events", "_unit_analysis_reads",
                "_unit_analysis_watches", "_value_flow"):
        assert selected[2][key] == legacy[2][key]


def test_related_writer_and_missing_future_key_keep_finite_path(tmp_path):
    prefix = "def first(): pass\ndef second(): pass\n"
    original = analyze(tmp_path, {"demo.py": prefix +
                       'def run():\n table={"go":first}\n table["go"]()\n'})
    changed = analyze(tmp_path, {"demo.py": prefix +
                      'def run():\n table={"go":first}\n table["go"]=second\n table["go"]()\n'})
    missing = analyze(tmp_path, {"demo.py": prefix +
                      'def run():\n table={}\n table["go"]()\n'})
    for graph, expected in ((original, {"first"}), (changed, {"second"}), (missing, set())):
        assert site(graph, "table['go']", "run")["names"] == expected
    assert original[2]["source_only_container_reads"] == 1
    assert changed[2]["source_only_container_reads"] == 0
    assert missing[2]["source_only_container_reads"] == 0
    assert missing[2]["_unit_subscriptions"]


def test_unrelated_fresh_writer_growth_keeps_read_checks_local(tmp_path):
    base = 'def target(): pass\ndef caller():\n table={"go":target}\n table["go"]()\n'
    for count in (0, 20, 100):
        noise = "".join(f"def writer_{i}():\n slot={{}}\n slot['x']={i}\n"
                        for i in range(count))
        graph = analyze(tmp_path, {"demo.py": base + noise})
        selected = site(graph, "table['go']", "caller")
        assert selected["names"] == {"target"}
        assert graph[2]["source_only_container_reads"] == 1
        assert graph[2]["slot_scope_candidates_checked"] == 1
        assert graph[2]["slot_writer_index_receivers"] == count


def test_global_literal_read_ignores_unrelated_function_bindings(tmp_path):
    base = 'def target(): pass\nregistry={"go":target}\ndef run(): registry["go"]()\n'
    for count in (0, 20, 100):
        noise = "".join(f"def writer_{i}():\n slot={{}}\n slot['x']={i}\n"
                        for i in range(count))
        graph = analyze(tmp_path, {"demo.py": base + noise})
        selected = site(graph, "registry['go']", "run")
        assert selected["names"] == {"target"}
        assert graph[2]["source_only_container_reads"] == 1
        assert graph[2]["slot_scope_candidates_checked"] == 2
        assert graph[2]["slot_events_checked"] == 0
        assert graph[2]["source_only_literal_entries_checked"] == 1
        assert graph[2]["slot_writer_index_receivers"] == count
        assert graph[2]["jedi_queries_executed"] == 1


def test_module_writer_origin_index_does_not_rescan_binding_prefixes(tmp_path, monkeypatch):
    original = Analyzer.reaching
    preparatory = []

    def observed(self, scope, name, before):
        if self._indexing_writer_origins and self.nodes[scope]["kind"] == "module":
            preparatory.append((scope, name, before))
        return original(self, scope, name, before)

    monkeypatch.setattr(Analyzer, "reaching", observed)
    base = 'def target(): pass\nregistry={"go":target}\ndef run(): registry["go"]()\n'
    for count in (0, 20, 100):
        preparatory.clear()
        noise = "".join(f"slot_{i}={{}}\nslot_{i}['x']={i}\n"
                        for i in range(count))
        graph = analyze(tmp_path, {"demo.py": base + noise})
        assert site(graph, "registry['go']", "run")["names"] == {"target"}
        assert graph[2]["slot_writer_index_receivers"] == count
        assert graph[2]["slot_origin_binding_index_entries"] == count + 1
        assert graph[2]["slot_scope_candidates_checked"] == 2
        assert graph[2]["slot_events_checked"] == 0
        assert len(preparatory) <= 1


def test_private_origin_query_reuses_raw_jedi_without_reusing_mapping(tmp_path):
    sources = {"base.py": 'def target(): pass\nregistry={"go":target}\n',
               "client.py": 'from base import registry as alias\nalias["x"]=1\n'
                            'def run(): alias["go"]()\n'}
    graph = analyze(tmp_path, sources)
    assert site(graph, "alias['go']", "run")["names"] == {"target"}
    assert graph[2]["slot_writer_index_receivers"] == 1
    assert graph[2]["jedi_raw_observation_hits"] >= 1
    assert graph[2]["jedi_queries_executed"] == graph[2]["jedi_queries"]


def test_unrelated_calls_have_one_time_source_footprint(tmp_path):
    base = ('def first(): pass\ndef noop(): pass\nhandlers={"go":first}\n'
            'def run(): handlers["go"]()\n')
    for count in (0, 20, 100):
        graph = analyze(tmp_path, {"demo.py": base + "noop()\n" * count})
        selected = site(graph, "handlers['go']", "run")
        assert selected["names"] == {"first"} and selected["complete"]
        assert graph[2]["source_only_container_reads"] == 1
        assert graph[2]["slot_scope_candidates_checked"] == 2
        assert graph[2]["slot_events_checked"] == 0
        assert graph[2]["source_only_literal_entries_checked"] == 1
        assert graph[2]["slot_call_index_events"] == count + 1


def test_actual_call_input_or_captured_mutation_stays_related(tmp_path):
    argument = ('def first(): pass\nhandlers={"go":first}\n'
                'def external(h): pass\nexternal(handlers)\n'
                'def run(): handlers["go"]()\n')
    changed = ('def first(): pass\ndef second(): pass\nhandlers={"go":first}\n'
               'def mutate(): handlers["go"]=second\nmutate()\n'
               'def run(): handlers["go"]()\n')
    for source in (argument, changed):
        graph = analyze(tmp_path, {"demo.py": source})
        assert graph[2]["source_only_container_reads"] == 0
        assert site(graph, "handlers['go']", "run")["names"]
    assert "container-mutation-or-escape" in site(
        analyze(tmp_path, {"demo.py": argument}), "handlers['go']", "run")["unresolved_reasons"]


def test_warm_origin_index_reuses_unselected_call_observations(tmp_path):
    for count in (0, 20, 100):
        config, repo = initialize(tmp_path / f"warm-{count}")
        (repo / "src/weights.py").unlink()
        (repo / "docs/guide.md").unlink()
        (repo / "src/utility.py").write_text("def noop(): pass\n")
        for number in range(count):
            (repo / f"src/noise_{number}.py").write_text(
                f"from utility import noop\ndef idle_{number}(): noop()\n")
        active = repo / "src/active.py"

        def source(target):
            return ("def first(): pass\ndef second(): pass\n"
                    f'handlers={{"go":{target}}}\ndef run(): handlers["go"]()\n')

        active.write_text(source("first"))
        with forbid_provider():
            build(config, offline=True, lexical_only=True)
        active.write_text(source("second"))
        with forbid_provider():
            updated = build(config, offline=True, lexical_only=True)
        assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        assert updated["incremental"]["analysis_scope"]["selected_owner_count"] == 4
        assert updated["graph"]["jedi_queries_executed"] == 1
        assert updated["graph"]["jedi_query_entries"] == 2
        assert updated["graph"]["slot_call_index_events"] == count + 1


def test_writer_index_preparation_does_not_publish_consumer_evidence(tmp_path, monkeypatch):
    original = Analyzer._ensure_slot_writer_index
    checked = []

    def observed(self):
        before = (set(self.unit_supports), set(self.unit_container_subscriptions),
                  set(self.unit_container_writes), set(self.unit_analysis_reads),
                  set(self.unit_input_events), set(self.analysis_reads),
                  self.analysis_inputs.export(), set(self.queries), set(self.memo))
        original(self)
        after = (set(self.unit_supports), set(self.unit_container_subscriptions),
                 set(self.unit_container_writes), set(self.unit_analysis_reads),
                 set(self.unit_input_events), set(self.analysis_reads),
                 self.analysis_inputs.export(), set(self.queries), set(self.memo))
        assert before == after
        checked.append(self.slot_writer_index_receivers)

    monkeypatch.setattr(Analyzer, "_ensure_slot_writer_index", observed)
    sources = {
        "base.py": "def target(): pass\nregistry={'go':target}\n",
        "client.py": """from base import registry
def mutate(bucket): bucket['x']=target
def producer(): return {}
returned=producer()
returned['x']=1
def run(): registry['go']()
""",
    }
    graph = analyze(tmp_path, sources)
    assert site(graph, "registry['go']", "run")["names"] == {"target"}
    assert checked and max(checked) >= 2
