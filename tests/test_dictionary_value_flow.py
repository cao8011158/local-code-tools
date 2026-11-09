"""Source-only dictionary writes, subscriptions and indexed local updates."""

import json
import sqlite3

import pytest

from lct.common import ToolError
from lct.storage import FileDependencies, build, current, manifest
from tests.synthetic_support import initialize
from tests.semantic_comparison import assert_semantic_equal
from tests.test_batch3_actual_acceptance import semantic


def setup(tmp_path, a, b, noise=0):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/a.py").write_text(a)
    (repo / "src/b.py").write_text(b)
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"def idle_{i}(): pass\n")
    return config, repo


def origin_rows(deps):
    return list(deps.db.execute(
        "select origin,key_kind,key,read_owner,consumer_owner from unit_container_subscriptions "
        "order by origin,key,read_owner"))


def test_separate_same_key_containers_have_distinct_source_origins(tmp_path):
    c, _ = setup(tmp_path, "def first(): pass\ndef second(): pass\n"
                 "one={'go':first}\ntwo={'go':second}\n",
                 "from a import one,two\ndef run():\n one['go']()\n two['go']()\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    assert meta["value_flow_coverage"] == "source-only-no-target-certificate"
    with FileDependencies(folder, meta) as deps:
        subscriptions = [r for r in origin_rows(deps) if r[2] == "string:go"]
        assert len({r[0] for r in subscriptions}) == 2
        assert all(deps.unit_container_readers(origin, "go") for origin, *_ in subscriptions)
        assert all(deps.unit_container_writes(origin, "go") for origin, *_ in subscriptions)
        assert all(any(r["key_relation"] == "other-conservative"
                       for r in deps.unit_container_readers(origin, "missing"))
                   for origin, *_ in subscriptions)
        with pytest.raises(ToolError):
            deps.entry_ids_for_file("synthetic-review", "src/a.py")


def test_missing_future_key_keeps_exact_negative_subscription(tmp_path):
    items = ",".join(f"'{i}':target" for i in range(105))
    c, repo = setup(tmp_path, f"def target(): pass\nregistry={{{items}}}\n",
                    "from a import registry\ndef run(): registry['missing']()\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    with FileDependencies(folder, meta) as deps:
        rows = [r for r in origin_rows(deps) if r[2] == "string:missing"]
        assert len(rows) == 1
        origin = rows[0][0]
        readers = deps.unit_container_readers(origin, "missing")
        assert any(r["read_location"]["expression"] == "registry['missing']"
                   for r in readers)
        plan = list(deps.db.execute("explain query plan select read_owner from "
                                    "unit_container_subscriptions where origin=? and key=?",
                                    (origin, "string:missing")))
        assert any("INDEX" in str(row).upper() for row in plan), plan
    (repo / "src/a.py").write_text(
        f"def target(): pass\nregistry={{{items}}}\nregistry['missing']=target\n")
    updated = build(c, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"


def test_unrelated_producer_dictionary_keeps_its_source_rows_without_reparse(tmp_path, monkeypatch):
    from lct import extract as extraction

    c, repo = setup(tmp_path, "def first(): pass\ndef second(): pass\nregistry={'go':first}\n",
                    "from a import registry\ndef run(): registry['go']()\n")
    (repo / "src/elsewhere.py").write_text("def unrelated(): pass\nother={'same':unrelated}\n")
    first = build(c, offline=True, lexical_only=True)
    old_folder, old_meta = manifest(c, first["version"])
    with FileDependencies(old_folder, old_meta) as deps:
        old = list(deps.db.execute("select data from unit_container_writes "
                                   "where json_extract(data,'$.producer_location.path')='src/elsewhere.py'"))
    assert old
    parsed = []
    original = extraction.python_nodes

    def count(file):
        parsed.append(file["path"])
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", count)
    (repo / "src/a.py").write_text(
        "def first(): pass\ndef second(): pass\nregistry={'go':second}\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert parsed == ["src/a.py"]
    folder, meta = manifest(c, changed["version"])
    with FileDependencies(folder, meta) as deps:
        retained = list(deps.db.execute("select data from unit_container_writes "
                                        "where json_extract(data,'$.producer_location.path')='src/elsewhere.py'"))
        assert len(retained) == len(old) == 1
        before, after = json.loads(old[0][0]), json.loads(retained[0][0])
        assert before.pop("producer_site") != after.pop("producer_site")
        assert before == after  # unchanged source, rebound into the new capture
    fresh_config = dict(c, data=str(tmp_path / "fresh"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(c, changed["version"]),
                          semantic(fresh_config, fresh["version"]))


def test_imported_and_local_alias_keep_source_subscription(tmp_path):
    c, _ = setup(tmp_path, "def target(): pass\nregistry={'go':target}\n",
                 "from a import registry as imported\nalias=imported\n"
                 "def run():\n local=alias\n local['go']()\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    with FileDependencies(folder, meta) as deps:
        subscriptions = [r for r in origin_rows(deps) if r[2] == "string:go"]
        assert len(subscriptions) == 1
        assert any(r["read_location"]["expression"] == "local['go']"
                   for r in deps.unit_container_readers(subscriptions[0][0], "go"))


@pytest.mark.parametrize("missing", ("schema", "coverage"))
def test_old_target_certificate_is_incompatible_and_does_not_publish(tmp_path, missing):
    c, repo = setup(tmp_path, "def target(): pass\nregistry={'go':target}\n",
                    "from a import registry\ndef run(): registry['go']()\n")
    first = build(c, offline=True, lexical_only=True)
    folder, summary = manifest(c, first["version"])
    changed = dict(summary)
    if missing == "schema":
        changed.pop("value_flow_schema")
    else:
        changed["value_flow_coverage"] = "partial"
    (folder / "summary.json").write_text(json.dumps(changed))
    (repo / "src/a.py").write_text("def target(): pass\ndef other(): pass\nregistry={'go':other}\n")
    previous = current(c)
    with pytest.raises(ToolError, match="Local update unavailable"):
        build(c, offline=True, lexical_only=True)
    assert current(c) == previous


@pytest.mark.parametrize("noise", (0, 20, 100))
def test_reverse_source_lookup_is_indexed_under_unrelated_growth(tmp_path, noise):
    c, repo = setup(tmp_path / str(noise),
                    "def target(): pass\nregistry={'go':target}\n",
                    "from a import registry\ndef run(): registry['go']()\n")
    for i in range(noise):
        (repo / f"src/other_{i}.py").write_text(
            f"def target_{i}(): pass\nregistry_{i}={{'go':target_{i}}}\n")
    built = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, built["version"])
    with FileDependencies(folder, meta) as deps:
        origin = next(r[0] for r in origin_rows(deps) if r[2] == "string:go"
                      and "src/a.py" in r[0])
        readers = deps.unit_container_readers(origin, "go")
        assert any(r["read_location"]["path"] == "src/b.py" for r in readers)
        plan = list(deps.db.execute("explain query plan select consumer_owner from "
                                    "unit_container_subscriptions where origin=? and key=?",
                                    (origin, "string:go")))
        assert any("INDEX" in str(row).upper() for row in plan)


@pytest.mark.parametrize("key_expression", ("True", "1", "1.0", "unknown_key"))
def test_key_forms_remain_locally_updateable_without_target_certificate(tmp_path, key_expression):
    c, repo = setup(tmp_path,
                    f"def target(): pass\nregistry={{{key_expression}:target}}\n",
                    "from a import registry\ndef run(): registry[True]()\n")
    build(c, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text(
        f"def target(): pass\ndef another(): pass\nregistry={{{key_expression}:another}}\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
