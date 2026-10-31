"""Source located dependency evidence without changing full graph resolution."""

import pytest

from lct.common import ToolError
from lct.dependency_origins import key_identity
from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def capture(tmp_path, sources):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for path, source in sources.items():
        (repo / "src" / path).write_text(source)
    built = build(config, offline=True, lexical_only=True)
    folder, summary = manifest(config, built["version"])
    return config, repo, folder, summary


def node_id(db, qualname):
    return next(r[0] for r in db.execute("select node_id from node_order")
                if r[0].split(":")[-1].startswith(qualname + "#"))


def test_two_callback_arguments_keep_distinct_provider_and_consumer_sites(tmp_path):
    _, _, folder, summary = capture(tmp_path, {"a.py":
        "def a(): pass\ndef b(): pass\ndef execute(first_cb, second_cb):\n"
        "    first_cb()\n    second_cb()\ndef run(): execute(a, b)\n"})
    with FileDependencies(folder, summary) as deps:
        execute, run = node_id(deps.db, "execute"), node_id(deps.db, "run")
        supports = [r for r in deps.unit_sources(execute)["supports"]
                    if r["kind"] == "actual-parameter"]
        assert len(supports) == 2
        assert {r["detail"]["parameter"]["name"]: r["detail"]["target_ids"][0]
                .split(":function:")[-1].split("#")[0] for r in supports} == {
                    "first_cb": "a", "second_cb": "b"}
        assert {r["producer_owner"] for r in supports} == {run}
        assert len({r["consumer_site"] for r in supports}) == 2
        assert all(r["detail"]["argument_source"]["call_site"] == r["producer_site"]
                   and r["producer_location"]["path"] == "src/a.py" for r in supports)
        assert {(execute, r["consumer_site"]) for r in supports} <= deps.unit_readers(run)
        assert {r["detail"]["parameter"]["name"] for r in deps.unit_sources(
            execute, supports[0]["consumer_site"])["supports"] if r["kind"] == "actual-parameter"} == {
            supports[0]["detail"]["parameter"]["name"]}


def test_getter_slot_read_retains_actual_read_and_final_consumer(tmp_path):
    _, _, folder, summary = capture(tmp_path, {
        "a.py": "def first(): pass\ndef second(): pass\n"
                "registry={'go': first, 'else': second}\n"
                "def get_callback(): return registry['go']\n",
        "b.py": "from a import get_callback\ndef run():\n"
                "    fn=get_callback()\n    fn()\n"})
    with FileDependencies(folder, summary) as deps:
        run = node_id(deps.db, "run")
        getter = node_id(deps.db, "get_callback")
        row = deps.db.execute("select origin from unit_container_subscriptions limit 1").fetchone()
        assert row is not None
        origin = row[0]
        readers = deps.unit_container_readers(origin, "go")
        assert any(r["read_owner"] == getter and r["consumer_owner"] == run
                   and r["key"] == "string:go" and r["key_relation"] == "same"
                   and r["read_location"]["expression"] == "registry['go']"
                   and r["consumer_location"]["path"] == "src/b.py"
                   for r in readers)
        # Different keys in one origin stay conservative invalidation inputs.
        assert any(r["key_relation"] == "other-conservative"
                   for r in deps.unit_container_readers(origin, "else"))
        assert {w["key"] for w in deps.unit_container_writes(origin)} >= {
            "string:go", "string:else"}
        assert any(s["kind"] == "container-writer" and s["detail"]["origin"] == origin
                   and s["detail"]["read_owner"] == getter
                   for s in deps.unit_sources(run)["supports"])


def test_missing_key_subscribes_to_future_writer_and_numeric_keys_agree(tmp_path):
    _, _, folder, summary = capture(tmp_path, {"a.py":
        "registry={}\ndef run(): registry['future']()\n"})
    with FileDependencies(folder, summary) as deps:
        origin = deps.db.execute("select origin from unit_container_subscriptions limit 1").fetchone()[0]
        assert deps.unit_container_readers(origin, "future")
        assert deps.unit_container_writes(origin, "future") == []
    assert key_identity(True) == key_identity(1) == key_identity(1.0)
    assert key_identity(None) != key_identity("None")


def test_identical_capture_inherits_evidence_and_owner_update_replaces_it(tmp_path):
    config, repo, folder, first = capture(tmp_path, {
        "a.py": "def target(): pass\ndef run(): target()\n",
        "b.py": "def idle(): pass\n"})
    with FileDependencies(folder, first) as deps:
        assert deps.origin_available
        initial_count = first["origin_support_count"]
    reused = build(config, offline=True, lexical_only=True)
    reused_folder, reused_meta = manifest(config, reused["version"])
    with FileDependencies(reused_folder, reused_meta) as deps:
        assert deps.origin_available
        assert reused_meta["origin_support_count"] == initial_count
    (repo / "src/a.py").write_text("def target(): pass\ndef run(): target()\n\n")
    updated = build(config, offline=True, lexical_only=True)
    local_folder, local_meta = manifest(config, updated["version"])
    mode = updated["incremental"]["analysis_scope"]["mode"]
    if mode == "incremental-owners":
        with FileDependencies(local_folder, local_meta) as deps:
            assert deps.origin_available
            assert deps.unit_sources(node_id(deps.db, "run"))["supports"]
    elif mode != "full-graph":
        with FileDependencies(local_folder, local_meta) as deps:
            assert not deps.origin_available
            with pytest.raises(ToolError):
                deps.unit_sources(node_id(deps.db, "run"))


def test_reverse_plans_use_origin_and_producer_indexes(tmp_path):
    _, _, folder, summary = capture(tmp_path, {
        "a.py": "def first(): pass\nregistry={'go':first}\n"
                "def run(): registry['go']()\n"})
    with FileDependencies(folder, summary) as deps:
        checks = (
            ("select consumer_owner from unit_source_supports where producer_owner=?",
             (node_id(deps.db, "first"),)),
            ("select consumer_owner from unit_container_subscriptions where origin=?",
             (deps.db.execute("select origin from unit_container_subscriptions limit 1").fetchone()[0],)),
        )
        for sql, params in checks:
            plan = [r[3] for r in deps.db.execute("explain query plan " + sql, params)]
            assert any("SEARCH" in step and "INDEX" in step for step in plan), plan
            assert not any("SCAN" in step for step in plan), plan


def test_legacy_origin_schema_is_unavailable_without_disabling_old_indexes(tmp_path):
    _, _, folder, summary = capture(tmp_path, {"a.py": "def target(): pass\n"})
    older = dict(summary, origin_dependency_schema=None)
    with FileDependencies(folder, older) as deps:
        assert not deps.origin_available
        with pytest.raises(ToolError):
            deps.unit_readers("unknown")
