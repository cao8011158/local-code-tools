"""Jedi owns container-call targets; source recorder keeps read/write origins."""

import jedi
import pytest

from lct.storage import build
from tests.test_python_pipeline import analyze, site
from tests.synthetic_support import forbid_provider, initialize


@pytest.mark.parametrize("literal,write,expected", [
    ('{"go":first}', '', {"first"}),
    ('{"go":first}', 'table["go"]=second', {"second"}),
    ('{}', '', set()),
])
def test_related_writer_and_missing_key_source(tmp_path, literal, write, expected):
    source = ("def first(): pass\ndef second(): pass\ndef run():\n"
              f" table={literal}\n {write}\n table['go']()\n")
    raw = jedi.Script(source).get_signatures(len(source.splitlines()), 13)
    assert {n.name for n in raw} == expected
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = site(graph, "table['go']", "run")
    assert observed["names"] == expected
    assert observed["target_provider"] == "jedi-get-signatures"
    subscriptions = graph[2]["_unit_subscriptions"]
    assert any(r["key"] == "string:go" and r["read_location"]["expression"] == "table['go']"
               for r in subscriptions)
    if write:
        assert any(r["key"] == "string:go" and r["kind"] == "subscript-write"
                   for r in graph[2]["_unit_writes"])
    if not expected:
        assert observed["unknown_origin"] and "jedi-no-result" in observed["unresolved_reasons"]


@pytest.mark.parametrize("count", (0, 20, 100))
def test_unrelated_fresh_writers_keep_literal_read_source_local(tmp_path, count):
    base = 'def target(): pass\ndef caller():\n table={"go":target}\n table["go"]()\n'
    noise = ''.join(f"def writer_{i}():\n slot={{}}\n slot['x']={i}\n" for i in range(count))
    graph = analyze(tmp_path, {"demo.py": base + noise})
    assert site(graph, "table['go']", "caller")["names"] == {"target"}
    related = [r for r in graph[2]["_unit_subscriptions"]
               if r["read_location"]["expression"] == "table['go']"]
    assert len(related) == 1 and related[0]["key"] == "string:go"


@pytest.mark.parametrize("count", (0, 20, 100))
def test_global_registry_read_ignores_unrelated_function_sources(tmp_path, count):
    base = 'def target(): pass\nregistry={"go":target}\ndef run(): registry["go"]()\n'
    noise = ''.join(f"def writer_{i}():\n slot={{}}\n slot['x']={i}\n" for i in range(count))
    graph = analyze(tmp_path, {"demo.py": base + noise})
    assert site(graph, "registry['go']", "run")["names"] == {"target"}
    related = [r for r in graph[2]["_unit_subscriptions"]
               if r["read_location"]["expression"] == "registry['go']"]
    assert len(related) == 1 and related[0]["key"] == "string:go"


def test_imported_alias_keeps_captured_source_read(tmp_path):
    graph = analyze(tmp_path, {
        "base.py": 'def target(): pass\nregistry={"go":target}\n',
        "client.py": 'from base import registry as alias\nalias["x"]=1\ndef run(): alias["go"]()\n',
    })
    assert site(graph, "alias['go']", "run")["names"] == {"target"}
    assert any(r["read_location"]["expression"] == "alias['go']"
               for r in graph[2]["_unit_subscriptions"])


@pytest.mark.parametrize("count", (0, 20, 100))
def test_unrelated_calls_do_not_change_literal_target_or_read_origin(tmp_path, count):
    base = 'def first(): pass\ndef noop(): pass\nhandlers={"go":first}\ndef run(): handlers["go"]()\n'
    graph = analyze(tmp_path, {"demo.py": base + "noop()\n" * count})
    assert site(graph, "handlers['go']", "run")["names"] == {"first"}
    related = [r for r in graph[2]["_unit_subscriptions"]
               if r["read_location"]["expression"] == "handlers['go']"]
    assert len(related) == 1 and related[0]["key"] == "string:go"


@pytest.mark.parametrize("count", (0, 20, 100))
def test_warm_origin_evidence_and_target_remain_local(tmp_path, count):
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
        old = build(config, offline=True, lexical_only=True)
    active.write_text(source("second"))
    with forbid_provider():
        updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert updated["graph"]["jedi_queries_executed"] == 3
    assert updated["graph"]["jedi_query_entries"] == 3
    assert old["version"] != updated["version"]
