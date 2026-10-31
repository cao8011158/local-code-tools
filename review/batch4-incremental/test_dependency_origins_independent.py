"""Root-owned Batch 1 checks through captured builds and FileDependencies."""
import json
import sqlite3

import pytest

from lct.common import ToolError
from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def fixture(tmp_path, sources):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for name, source in sources.items():
        path = repo / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    built = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, built["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = [json.loads(raw) for (raw,) in db.execute("select data from nodes")]
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for (raw,) in db.execute("select data from sites")]
    return config, repo, built, folder, meta, nodes, sites


def owner(nodes, path, qualname, kind="function"):
    found = [n["node_id"] for n in nodes if n["path"] == "src/" + path
             and n["qualname"] == qualname and n["kind"] == kind]
    assert len(found) == 1, found
    return found[0]


def at(sites, ident, expression):
    found = [s for s in sites if s["execution_owner"] == ident
             and s["expression"] == expression]
    assert len(found) == 1, found
    return found[0]


def sources(deps, ident, site=None, kind=None):
    page = deps.unit_sources(ident, site)
    assert page["has_more"] is False
    return [r for r in page["supports"] if kind is None or r["kind"] == kind]


def test_repeated_call_sites_have_independent_definition_supports(tmp_path):
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        "provider.py": "def target(): pass\n",
        "consumer.py": "from provider import target\ndef run():\n    target()\n    target()\n"})
    target = owner(nodes, "provider.py", "target")
    run = owner(nodes, "consumer.py", "run")
    expected = {s["site_id"] for s in sites if s["execution_owner"] == run}
    assert len(expected) == 2
    with FileDependencies(folder, meta) as deps:
        rows = sources(deps, run, kind="call-target")
        matched = [r for r in rows if r["producer_owner"] == target]
        assert {r["consumer_site"] for r in matched} == expected
        assert deps.unit_readers(target) == {(run, site) for site in expected}
        for row in matched:
            assert row["producer_location"]["path"] == "src/provider.py"
            assert row["consumer_location"]["path"] == "src/consumer.py"
            assert deps.unit_readers(target, row["producer_site"]) == {
                (run, site) for site in expected}
            assert all(r["consumer_site"] == row["consumer_site"]
                       for r in sources(deps, run, row["consumer_site"]))
        with pytest.raises(ToolError, match="byte budget"):
            deps.unit_sources(run, max_bytes=1)


def test_two_callback_parameters_keep_their_actual_argument_and_consumption_site(tmp_path):
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        "provider.py": "from worker import execute\ndef first(): pass\ndef second(): pass\n"
                       "def run(): execute(first, two=second)\n",
        "worker.py": "def execute(one, *, two):\n    one()\n    two()\n"})
    run = owner(nodes, "provider.py", "run")
    execute = owner(nodes, "worker.py", "execute")
    with FileDependencies(folder, meta) as deps:
        for parameter, target, argument_kind in (("one", "first", "positional"),
                                                  ("two", "second", "keyword")):
            call = at(sites, execute, parameter)
            rows = sources(deps, execute, call["site_id"], "actual-parameter")
            assert rows, (parameter, rows)
            assert {r["producer_owner"] for r in rows} == {run}
            assert {r["detail"]["parameter"]["name"] for r in rows} == {parameter}
            assert {r["detail"]["argument_source"]["kind"] for r in rows} == {argument_kind}
            target_id = owner(nodes, "provider.py", target)
            assert any(target_id in r["detail"]["target_ids"] for r in rows)
            assert all(r["producer_location"]["path"] == "src/provider.py" for r in rows)
            assert all(r["consumer_location"]["path"] == "src/worker.py" for r in rows)
            assert all(r["consumer_location"]["line"] == call["line"] for r in rows)
            assert (execute, call["site_id"]) in deps.unit_readers(run)


def test_default_callback_records_definition_source_and_preserves_open_input(tmp_path):
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        "worker.py": "def fallback(): pass\ndef execute(callback=fallback): callback()\n",
        "provider.py": "from worker import execute\ndef run(): execute()\n"})
    execute = owner(nodes, "worker.py", "execute")
    call = at(sites, execute, "callback")
    assert call["unknown_origin"] is True
    with FileDependencies(folder, meta) as deps:
        rows = sources(deps, execute, call["site_id"], "default-parameter")
        assert rows
        assert all(r["producer_owner"] == owner(nodes, "worker.py", "worker", "module")
                   for r in rows)
        assert all(r["detail"]["parameter"]["name"] == "callback" for r in rows)
        assert any(owner(nodes, "worker.py", "fallback") in r["detail"]["target_ids"]
                   for r in rows)
    assert meta["origin_dependency_coverage"] == "observed-source-supports-partial"


def test_same_key_in_different_containers_keeps_distinct_origins(tmp_path):
    _, _, _, folder, meta, nodes, _ = fixture(tmp_path, {
        "a.py": "def first(): pass\nregistry={'go':first}\n",
        "c.py": "def second(): pass\nregistry={'go':second}\n",
        "consumer.py": "from a import registry as one\nfrom c import registry as two\n"
                       "def left(): one['go']()\ndef right(): two['go']()\n"})
    left = owner(nodes, "consumer.py", "left")
    right = owner(nodes, "consumer.py", "right")
    with FileDependencies(folder, meta) as deps:
        left_sources = sources(deps, left, kind="container-writer")
        right_sources = sources(deps, right, kind="container-writer")
        assert left_sources and right_sources
        first_origins = {r["detail"]["origin"] for r in left_sources}
        second_origins = {r["detail"]["origin"] for r in right_sources}
        assert first_origins.isdisjoint(second_origins)
        for origin in first_origins:
            assert {r["consumer_owner"] for r in deps.unit_container_readers(origin, "go")} == {left}
        for origin in second_origins:
            assert {r["consumer_owner"] for r in deps.unit_container_readers(origin, "go")} == {right}


def test_missing_key_range_and_equal_numeric_keys_remain_subscribed(tmp_path):
    _, _, _, folder, meta, nodes, _ = fixture(tmp_path, {
        "provider.py": "def target(): pass\nregistry={1:target, None:target}\n",
        "consumer.py": "from provider import registry\ndef known(): registry[True]()\n"
                       "def missing(): registry['future']()\n"
                       "def dynamic(key): registry[key]()\n"
                       "def none(): registry[None]()\n"})
    known = owner(nodes, "consumer.py", "known")
    missing = owner(nodes, "consumer.py", "missing")
    dynamic = owner(nodes, "consumer.py", "dynamic")
    none = owner(nodes, "consumer.py", "none")
    with FileDependencies(folder, meta) as deps:
        rows = sources(deps, known, kind="container-writer")
        assert rows
        origin = rows[0]["detail"]["origin"]
        for key in (True, 1, 1.0):
            selected = deps.unit_container_readers(origin, key)
            assert known in {r["consumer_owner"] for r in selected}
            assert dynamic in {r["consumer_owner"] for r in selected if r["key_kind"] == "range"}
        future = deps.unit_container_readers(origin, "future")
        assert any(r["consumer_owner"] == missing and r["key_kind"] == "exact" for r in future)
        assert any(r["consumer_owner"] == none and r["key_kind"] == "exact"
                   and r["key_relation"] == "same" for r in deps.unit_container_readers(origin, None))
        assert not deps.unit_container_writes(origin, "future")
        assert {r["consumer_owner"] for r in deps.unit_container_readers(origin)} >= {
            known, missing, dynamic, none}


def test_getter_memo_transfers_dictionary_sources_to_each_final_consumer(tmp_path):
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        "provider.py": "def first(): pass\ndef second(): pass\nregistry={'go':first}\n"
                       "def get_callback(): return registry['go']\n",
        "writer.py": "from provider import registry, second\nregistry['go']=second\n",
        "consumer.py": "from provider import get_callback\ndef one():\n    fn=get_callback()\n    fn()\n"
                       "def two():\n    fn=get_callback()\n    fn()\n"})
    writer = owner(nodes, "writer.py", "writer", "module")
    getter = owner(nodes, "provider.py", "get_callback")
    with FileDependencies(folder, meta) as deps:
        for name in ("one", "two"):
            consumer = owner(nodes, "consumer.py", name)
            call = at(sites, consumer, "fn")
            rows = sources(deps, consumer, call["site_id"], "container-writer")
            assert writer in {r["producer_owner"] for r in rows}, (name, rows)
            assert all(r["consumer_location"]["path"] == "src/consumer.py" for r in rows)
            assert all(r["consumer_location"]["line"] == call["line"] for r in rows)
            assert any(r["detail"]["read_owner"] == getter for r in rows)
            assert any(r["producer_location"]["path"] == "src/writer.py" for r in rows)
            assert call["unknown_origin"] is True  # source edges do not improve runtime-order precision
        consumers = deps.unit_readers(writer)
        assert {owner(nodes, "consumer.py", n) for n in ("one", "two")} <= {
            ident for ident, _ in consumers}


def test_bounded_source_inspection_does_not_truncate_impact_readers(tmp_path):
    functions = "".join(f"def use_{i}(): target()\n" for i in range(105))
    _, _, _, folder, meta, nodes, _ = fixture(tmp_path, {
        "provider.py": "def target(): pass\n",
        "consumer.py": "from provider import target\n" + functions})
    target = owner(nodes, "provider.py", "target")
    with FileDependencies(folder, meta) as deps:
        readers = deps.unit_readers(target)
        expected = {owner(nodes, "consumer.py", f"use_{i}") for i in range(105)}
        assert {consumer for consumer, _ in readers} == expected
        single = owner(nodes, "consumer.py", "use_0")
        page = deps.unit_sources(single, limit=1)
        assert len(page["supports"]) == 1
        assert isinstance(page["has_more"], bool)
        with pytest.raises(ToolError):
            deps.unit_sources(single, limit=0)


def test_identical_capture_preserves_sources_and_old_schema_is_explicit(tmp_path):
    config, _, built, folder, meta, nodes, _ = fixture(tmp_path, {
        "provider.py": "def target(): pass\n",
        "consumer.py": "from provider import target\ndef run(): target()\n"})
    run = owner(nodes, "consumer.py", "run")
    with FileDependencies(folder, meta) as deps:
        previous = sources(deps, run)
    assert previous
    identical = build(config, offline=True, lexical_only=True)
    current_folder, current_meta = manifest(config, identical["version"])
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    with FileDependencies(current_folder, current_meta) as deps:
        assert sources(deps, run) == previous
    with FileDependencies(folder, meta) as deps:
        assert sources(deps, run) == previous
    unsupported = dict(current_meta, origin_dependency_schema=999)
    with FileDependencies(current_folder, unsupported) as deps:
        with pytest.raises(ToolError, match="source-origin"):
            deps.unit_sources(run)


def test_known_owner_and_container_queries_remain_indexed_under_unrelated_growth(tmp_path):
    measurements = []
    for unrelated in (0, 20, 100):
        text = {
            "provider.py": "def target(): pass\nregistry={'go':target}\n",
            "consumer.py": "from provider import registry\ndef run(): registry['go']()\n"}
        for i in range(unrelated):
            text[f"noise_{i}.py"] = (
                f"def other_{i}(): pass\nregistry={{'go':other_{i}}}\n"
                f"def use_{i}(): registry['go']()\n")
        _, _, _, folder, meta, nodes, _ = fixture(tmp_path / str(unrelated), text)
        consumer = owner(nodes, "consumer.py", "run")
        producer = owner(nodes, "provider.py", "target")
        with FileDependencies(folder, meta) as deps:
            rows = sources(deps, consumer, kind="container-writer")
            assert rows
            origin = rows[0]["detail"]["origin"]
            samples = []
            for _ in range(2):
                ticks, queries = [0], []
                def tick():
                    ticks[0] += 1
                    return 0
                deps.db.set_trace_callback(queries.append)
                deps.db.set_progress_handler(tick, 1)
                source_page = deps.unit_sources(consumer)
                readers = deps.unit_readers(producer)
                subscriptions = deps.unit_container_readers(origin, "go")
                deps.db.set_progress_handler(None, 0)
                deps.db.set_trace_callback(None)
                assert source_page["supports"] and not source_page["has_more"]
                assert {r[0] for r in readers} == {consumer}
                assert {r["consumer_owner"] for r in subscriptions} == {consumer}
                for sql in queries:
                    assert sql.lstrip().lower().startswith("select"), sql
                    plan = [r[3] for r in deps.db.execute("explain query plan " + sql)]
                    assert any("SEARCH" in step and "INDEX" in step for step in plan), plan
                    assert not any("SCAN" in step for step in plan), plan
                samples.append(dict(vm_steps=ticks[0], sql_count=len(queries),
                                    supports=len(source_page["supports"]), readers=len(readers),
                                    subscriptions=len(subscriptions)))
            # SQLite may execute a fixed initialization path on the first use
            # of a prepared statement. Compare cold and warm work separately.
            assert {k: v for k, v in samples[0].items() if k != "vm_steps"} == {
                k: v for k, v in samples[1].items() if k != "vm_steps"}, samples
            measurements.append(samples)
    assert measurements[1] == measurements[2], measurements
    for phase in (0, 1):
        observed = [group[phase] for group in measurements]
        assert {m["supports"] for m in observed} == {observed[0]["supports"]}
        assert {m["readers"] for m in observed} == {observed[0]["readers"]}
        assert {m["subscriptions"] for m in observed} == {observed[0]["subscriptions"]}
        # The smallest index may end at EOF instead of checking a following key.
        assert abs(observed[0]["vm_steps"] - observed[1]["vm_steps"]) <= (
            2 * observed[1]["sql_count"]), measurements
    print({"origin_lookup_measurements": measurements})


def test_origin_budget_remains_explicit_without_damaging_call_results(tmp_path, monkeypatch):
    import lct.python_analysis as analysis
    monkeypatch.setattr(analysis, "ORIGIN_LIMIT", 1)
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        "one.py": "def target(): pass\ndef run():\n    target()\n    target()\n"})
    run = owner(nodes, "one.py", "run")
    assert len([s for s in sites if s["execution_owner"] == run]) == 2
    assert meta["origin_dependency_truncated"] is True
    assert meta["origin_dependency_coverage"] == "unavailable"
    with FileDependencies(folder, meta) as deps:
        with pytest.raises(ToolError, match="source-origin"):
            deps.unit_sources(run)


def test_instance_container_origins_preserve_existing_allocation_identity(tmp_path):
    _, _, _, folder, meta, nodes, _ = fixture(tmp_path, {"one.py":
        "def first(): pass\ndef second(): pass\n"
        "class Box:\n    def __init__(self, callback):\n        self.handlers={'go':callback}\n"
        "one=Box(first)\ntwo=Box(second)\n"
        "def left(): one.handlers['go']()\n"
        "def right(): two.handlers['go']()\n"})
    left = owner(nodes, "one.py", "left")
    right = owner(nodes, "one.py", "right")
    with FileDependencies(folder, meta) as deps:
        one = sources(deps, left, kind="container-writer")
        two = sources(deps, right, kind="container-writer")
        assert one and two
        first_origins = {r["detail"]["origin"] for r in one}
        second_origins = {r["detail"]["origin"] for r in two}
        assert first_origins.isdisjoint(second_origins), (first_origins, second_origins)
