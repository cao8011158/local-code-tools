"""Independent public changed-Python update controls and actual parse counts."""

import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


A = "from b import execute\ndef first(): pass\ndef second(): pass\ndef run():\n    execute(first)\n"
B = "def execute(callback):\n    callback()\n"
U = "def leaf(): pass\ndef unrelated():\n    leaf()\n"


def records(c, version):
    folder, _ = manifest(c, version)
    result = {}
    for filename, tables in (
        ("catalog.sqlite", ("nodes", "edges")),
        ("graph-sites.sqlite", ("sites", "import_requests", "import_dependencies", "query_observations")),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                result[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                       for row in db.execute(f"select data from {table}"))
    return result


def fixture(tmp_path, noise):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "src/a.py").write_text(A)
    (repo / "src/b.py").write_text(B)
    (repo / "src/u.py").write_text(U)
    for i in range(noise):
        (repo / "src" / f"noise_{i}.py").write_text(U)
    return c, repo


@pytest.mark.parametrize("noise", [0, 20])
def test_callback_target_change_local_and_fresh_equal_then_failed_retry(tmp_path, monkeypatch, noise):
    c, repo = fixture(tmp_path, noise)
    initial = build(c, offline=True, lexical_only=True)
    old = records(c, initial["version"])
    (repo / "src/a.py").write_text(A.replace("execute(first)", "execute(second)"))
    calls = []
    actual = extraction.python_nodes

    def counted(file):
        calls.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    changed = build(c, offline=True, lexical_only=True)
    assert sorted(calls) == ["src/a.py", "src/b.py"], calls
    assert records(c, initial["version"]) == old
    local = records(c, changed["version"])
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert local == records(oracle, full["version"])
    # Exercise a second incremental generation and a failed publication.
    (repo / "src/a.py").write_text(A)
    calls.clear()
    with pytest.raises(ToolError, match="Injected interruption"):
        build(c, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(c) == changed["version"]
    assert records(c, changed["version"]) == local
    assert sorted(calls) == ["src/a.py", "src/b.py"]
    calls.clear()
    retried = build(c, offline=True, lexical_only=True)
    assert sorted(calls) == ["src/a.py", "src/b.py"]
    assert records(c, retried["version"]) == old


def test_new_import_pulls_previously_disconnected_module_into_component(tmp_path, monkeypatch):
    c, repo = fixture(tmp_path, 4)
    build(c, offline=True, lexical_only=True)
    changed_source = A.replace("from b import execute", "from b import execute\nfrom u import leaf")
    changed_source = changed_source.replace("execute(first)", "execute(leaf)")
    (repo / "src/a.py").write_text(changed_source)
    calls = []
    actual = extraction.python_nodes

    def counted(file):
        calls.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    changed = build(c, offline=True, lexical_only=True)
    assert sorted(calls) == ["src/a.py", "src/b.py", "src/u.py"]
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, changed["version"]) == records(oracle, full["version"])


def test_returned_function_and_keyword_callback_propagate_across_three_files(tmp_path, monkeypatch):
    c, repo = fixture(tmp_path, 5)
    source = "def first(): pass\ndef second(): pass\ndef factory():\n    return first\n"
    (repo / "src/a.py").write_text(source)
    (repo / "src/b.py").write_text(
        "from a import factory\nfrom c import execute\ndef main():\n    execute(callback=factory())\n")
    (repo / "src/c.py").write_text(B)
    build(c, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text(source.replace("return first", "return second"))
    parsed = []
    actual = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    changed = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ["src/a.py", "src/b.py", "src/c.py"]
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, changed["version"]) == records(oracle, full["version"])
