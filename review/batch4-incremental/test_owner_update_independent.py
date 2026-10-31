"""Root-owned acceptance: public update, semantic oracle, actual solver work."""
import json
from pathlib import Path
import sqlite3

import pytest

from lct.common import ToolError
from lct.python_analysis import Analyzer
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


CALLER = """from worker import execute
def first() -> int: return 1
def second() -> int: return 2
def run():
    execute(first)
"""
WORKER = """def execute(callback):
    callback()
def isolated_leaf(value: int) -> int:
    return value + 1
def unrelated(value: int) -> int:
    return isolated_leaf(value)
"""


def fixture(tmp_path, sources, noise=0):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for name, text in sources.items():
        path = repo / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(
            f"def leaf_{i}(x: int) -> int: return x + {i}\n"
            f"def active_{i}(x: int) -> int: return leaf_{i}(x)\n")
    return c, repo


def records(c, version):
    folder, meta = manifest(c, version)
    result = {}
    groups = (("catalog.sqlite", ("nodes", "edges")),
              ("graph-sites.sqlite", ("sites", "query_observations", "import_requests",
               "import_dependencies", "analysis_reads", "analysis_watches",
               "analysis_input_scopes", "analysis_input_members", "analysis_input_consumers",
               "value_nodes", "value_edges", "value_reads", "simple_python_certificates",
               "passive_python_certificates", "unit_dependencies", "unit_name_watches")))
    for filename, tables in groups:
        with sqlite3.connect(folder / filename) as db:
            available = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
            for table in tables:
                if table not in available:
                    continue
                columns = {r[1] for r in db.execute(f"pragma table_info({table})")}
                if "data" in columns:
                    rows = [json.dumps(json.loads(raw), sort_keys=True)
                            for (raw,) in db.execute(f"select data from {table}")]
                else:
                    rows = list(db.execute(f"select * from {table}"))
                result[table] = sorted(rows)
    result["meta"] = {key: meta.get(key) for key in (
        "simple_python_certificate", "value_flow_coverage", "analysis_input_coverage")}
    return result


def oracle(c, version, tmp_path, label="oracle"):
    other = dict(c, data=str(tmp_path / label))
    full = build(other, offline=True, lexical_only=True)
    got, expected = records(c, version), records(other, full["version"])
    for table in expected.keys() | got.keys():
        assert got.get(table) == expected.get(table), table


def targets(c, version, owner, expression):
    folder, _ = manifest(c, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        names = {json.loads(r[0])["node_id"]: json.loads(r[0])["qualname"]
                 for r in db.execute("select data from nodes")}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(r[0]) for r in db.execute("select data from sites")]
    selected = [s for s in sites if names.get(s["execution_owner"]) == owner
                and s["expression"] == expression]
    assert len(selected) == 1, selected
    return {names.get(target, target) for target in selected[0]["targets"]}


@pytest.mark.parametrize("noise", [0, 20])
def test_callback_retargets_without_solving_unrelated_functions(tmp_path, monkeypatch, noise):
    c, repo = fixture(tmp_path, {"caller.py": CALLER, "worker.py": WORKER}, noise)
    first = build(c, offline=True, lexical_only=True)
    before = records(c, first["version"])
    (repo / "src/caller.py").write_text(CALLER.replace("execute(first)", "execute(second)"))
    queried = []
    original = Analyzer.query
    def observe(self, scope, expr, **kwargs):
        queried.append(self.nodes[scope]["qualname"])
        return original(self, scope, expr, **kwargs)
    monkeypatch.setattr(Analyzer, "query", observe)
    updated = build(c, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert "unrelated" not in queried, queried
    assert not any(name.startswith("active_") for name in queried), queried
    assert scope["reused_owner_count"] >= noise + 1
    assert targets(c, updated["version"], "execute", "callback") == {"second"}
    assert records(c, first["version"]) == before
    monkeypatch.setattr(Analyzer, "query", original)
    oracle(c, updated["version"], tmp_path)
    # The result of an incremental build must itself support the next update.
    (repo / "src/caller.py").write_text(CALLER)
    queried.clear()
    monkeypatch.setattr(Analyzer, "query", observe)
    restored = build(c, offline=True, lexical_only=True)
    assert restored["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert "unrelated" not in queried and not any(n.startswith("active_") for n in queried)
    assert targets(c, restored["version"], "execute", "callback") == {"first"}
    monkeypatch.setattr(Analyzer, "query", original)
    oracle(c, restored["version"], tmp_path, "oracle-restored")


def test_multiple_callers_retain_other_producer(tmp_path):
    c, repo = fixture(tmp_path, {"caller.py": CALLER, "worker.py": WORKER,
        "other.py": "from caller import first\nfrom worker import execute\ndef other(): execute(first)\n"})
    build(c, offline=True, lexical_only=True)
    (repo / "src/caller.py").write_text(CALLER.replace("execute(first)", "execute(second)"))
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert targets(c, updated["version"], "execute", "callback") == {"first", "second"}
    oracle(c, updated["version"], tmp_path)


def test_parameter_detection_uses_ast_with_call_in_default(tmp_path):
    worker = WORKER.replace("def execute(callback):", "def default(): return None\n"
                           "def execute(callback=default()):")
    c, repo = fixture(tmp_path, {"caller.py": CALLER, "worker.py": worker})
    build(c, offline=True, lexical_only=True)
    (repo / "src/caller.py").write_text(CALLER.replace("execute(first)", "execute(second)"))
    updated = build(c, offline=True, lexical_only=True)
    assert targets(c, updated["version"], "execute", "callback") == {"second"}
    oracle(c, updated["version"], tmp_path)


def test_changed_return_value_reaches_callback_argument_consumers(tmp_path):
    provider = ("def first() -> int: return 1\ndef second() -> int: return 2\n"
                "def provide(): return first\n")
    c, repo = fixture(tmp_path, {"provider.py": provider, "worker.py": WORKER,
        "bridge.py": "from worker import execute\ndef forward(cb): execute(cb)\n",
        "driver.py": "from provider import provide\nfrom bridge import forward\n"
                     "def drive(): forward(provide())\n"}, 3)
    build(c, offline=True, lexical_only=True)
    (repo / "src/provider.py").write_text(provider.replace("return first", "return second"))
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert targets(c, updated["version"], "execute", "callback") == {"second"}
    oracle(c, updated["version"], tmp_path)


@pytest.mark.parametrize("kind", ["dictionary", "returned"])
def test_function_value_through_unchanged_forwarders(tmp_path, kind):
    provider = ("def first() -> int: return 1\ndef second() -> int: return 2\n"
                + ("registry={'go':first}\n" if kind == "dictionary"
                   else "def get_callback(): return first\n"))
    forward = ("from provider import registry\ndef get_callback(): return registry['go']\n"
               if kind == "dictionary" else "from provider import get_callback\n")
    c, repo = fixture(tmp_path, {"provider.py": provider, "forward.py": forward,
        "consumer.py": "from forward import get_callback\ndef run():\n    fn=get_callback()\n    fn()\n"}, 5)
    build(c, offline=True, lexical_only=True)
    (repo / "src/provider.py").write_text(provider.replace("'go':first", "'go':second").replace(
        "return first", "return second"))
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert targets(c, updated["version"], "run", "fn") == {"second"}
    oracle(c, updated["version"], tmp_path)


def test_nonempty_dictionary_evidence_survives_owner_update(tmp_path):
    provider = "def first(): pass\ndef second(): pass\nregistry={'go':first}\n"
    c, repo = fixture(tmp_path, {"provider.py": provider,
        "consumer.py": "from provider import registry\ndef run(): registry['go']()\n",
        "other.py": "def other(): pass\nregistry={'else':other}\n",
        "idle.py": "from other import registry\ndef unused(): registry['else']()\n"})
    old = build(c, offline=True, lexical_only=True)
    before = records(c, old["version"])
    assert before["value_nodes"] and before["value_edges"] and before["value_reads"]
    (repo / "src/provider.py").write_text(provider.replace("'go':first", "'go':second"))
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert targets(c, updated["version"], "run", "registry['go']") == {"second"}
    assert records(c, old["version"]) == before
    oracle(c, updated["version"], tmp_path)


def test_absent_provider_then_delete_and_failed_publication(tmp_path):
    c, repo = fixture(tmp_path, {"consumer.py": "from provider import chosen\ndef run(): chosen()\n"}, 4)
    first = build(c, offline=True, lexical_only=True)
    previous = records(c, first["version"])
    provider = repo / "src/provider.py"
    provider.write_text("def chosen() -> int: return 1\n")
    with pytest.raises(ToolError, match="Injected interruption"):
        build(c, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(c) == first["version"]
    assert records(c, first["version"]) == previous
    added = build(c, offline=True, lexical_only=True)
    assert targets(c, added["version"], "run", "chosen") == {"chosen"}
    oracle(c, added["version"], tmp_path, "oracle-added")
    provider.unlink()
    deleted = build(c, offline=True, lexical_only=True)
    assert targets(c, deleted["version"], "run", "chosen") == set()
    oracle(c, deleted["version"], tmp_path, "oracle-deleted")


def test_reverse_owner_lookups_use_indexes_under_unrelated_growth():
    from lct import unit_evidence
    measured = []
    for unrelated in (0, 20, 100):
        with sqlite3.connect(":memory:") as db:
            identities = ["provider", "consumer"] + [
                name for i in range(unrelated) for name in (f"other_{i}", f"leaf_{i}")]
            nodes = [dict(node_id=n, kind="function", module="mod") for n in identities]
            edges = [dict(source="consumer", target="provider", kind="REFERENCES")]
            edges += [dict(source=f"other_{i}", target=f"leaf_{i}", kind="REFERENCES")
                      for i in range(unrelated)]
            sites = [dict(expression="chosen", execution_owner="consumer")]
            sites += [dict(expression=f"unknown_{i}", execution_owner=f"other_{i}")
                      for i in range(unrelated)]
            unit_evidence.dependencies(db, nodes, edges, sites, [])
            for sql in ("select consumer from unit_dependencies where producer=?",
                        "select consumer from unit_name_watches where name=?"):
                plan = [r[3] for r in db.execute("explain query plan " + sql, ("provider",))]
                assert any("SEARCH" in p and "INDEX" in p for p in plan), plan
                assert not any("SCAN" in p for p in plan), plan
            steps = [0]
            def tick():
                steps[0] += 1
                return 0
            db.set_progress_handler(tick, 1)
            assert unit_evidence.readers(db, "provider") == {"consumer"}
            assert unit_evidence.name_readers(db, "chosen") == {"consumer"}
            db.set_progress_handler(None, 0)
            measured.append(steps[0])
    # A one-row index ends at EOF; a larger one checks the next key once.
    # No work may grow with unrelated rows after that boundary check appears.
    assert max(measured) - min(measured) <= 1 and measured[1] == measured[2], measured


def test_new_module_attribute_write_inside_changed_function_matches_full(tmp_path):
    writer = "import worker\ndef mutate():\n    return None\n"
    c, repo = fixture(tmp_path, {"writer.py": writer, "worker.py": WORKER})
    build(c, offline=True, lexical_only=True)
    (repo / "src/writer.py").write_text(writer.replace(
        "return None", "worker.isolated_leaf = worker.execute"))
    updated = build(c, offline=True, lexical_only=True)
    oracle(c, updated["version"], tmp_path)


def test_real_complex_item_unit_results_reused_after_execution_literal_edit(tmp_path, monkeypatch):
    root = Path(__file__).parent / "fixtures"
    sources = {}
    for name, subset in (("item_units.py", "actual-source-subset"),
                         ("errors.py", "actual-source-subset"),
                         ("_execution.py", "actual-related-source")):
        relative = "trpg_state_machine/" + name
        sources[relative] = (root / subset / "src" / relative).read_text()
    c, repo = fixture(tmp_path, sources)
    first = build(c, offline=True, lexical_only=True)
    before = records(c, first["version"])
    path = repo / "src/trpg_state_machine/_execution.py"
    path.write_text(path.read_text().replace('"actor"', '"actor_changed"', 1))
    queried = []
    original = Analyzer.query
    def observe(self, scope, expr, **kwargs):
        queried.append(self.nodes[scope]["qualname"])
        return original(self, scope, expr, **kwargs)
    monkeypatch.setattr(Analyzer, "query", observe)
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert "valid_item_unit" not in queried, queried
    assert records(c, first["version"]) == before
    monkeypatch.setattr(Analyzer, "query", original)
    oracle(c, updated["version"], tmp_path)
