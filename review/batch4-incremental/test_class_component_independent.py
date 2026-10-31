"""Root review controls for constructor state, bound methods and isolated classes."""

import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.storage import build, manifest
from tests.synthetic_support import initialize


SOURCE = '''"""Factory and mutable per-instance callback."""
def first(): pass
def second(): pass
class Box:
    """Holds a callback on its own instance."""
    def __init__(self):
        self.cb = first
    def invoke(self, callback):
        callback()
def factory():
    return Box()
'''
CONSUMER = '''from a import factory
def use():
    value = factory()
    value.cb()
'''
ISOLATED = '''def first(): pass
class Box:
    def __init__(self):
        self.cb = first
def unrelated():
    return Box()
def inspect():
    unrelated().cb()
'''


def records(c, version):
    folder, _ = manifest(c, version)
    result = {}
    for filename, tables in (
        ("catalog.sqlite", ("nodes", "edges")),
        ("graph-sites.sqlite", ("sites", "query_observations", "import_dependencies", "import_requests")),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                result[table] = sorted(json.dumps(json.loads(r[0]), sort_keys=True)
                                       for r in db.execute(f"select data from {table}"))
    return result


def fixture(tmp_path, noise, consumer=CONSUMER):
    c, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "src/a.py").write_text(SOURCE)
    (repo / "src/b.py").write_text(consumer)
    (repo / "src/u.py").write_text(ISOLATED)
    for i in range(noise):
        (repo / "src" / f"unrelated_{i}.py").write_text(ISOLATED)
    return c, repo


@pytest.mark.parametrize("noise", [0, 20])
def test_constructor_field_changes_with_factory_unchanged(tmp_path, monkeypatch, noise):
    c, repo = fixture(tmp_path, noise)
    old = build(c, offline=True, lexical_only=True)
    previous = records(c, old["version"])
    (repo / "src/a.py").write_text(SOURCE.replace("self.cb = first", "self.cb = second"))
    parsed = []
    actual = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == sorted(["src/a.py"] + [str(p.relative_to(repo)) for p in (repo / "src").glob("*.py")]), parsed
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, updated["version"]) == records(oracle, full["version"])
    assert records(c, old["version"]) == previous


def test_saved_bound_method_callback_changes_without_double_self(tmp_path, monkeypatch):
    consumer = '''from a import factory, first, second
def use():
    value = factory()
    saved = value.invoke
    saved(first)
'''
    c, repo = fixture(tmp_path, 3, consumer)
    old = build(c, offline=True, lexical_only=True)
    (repo / "src/b.py").write_text(consumer.replace("saved(first)", "saved(second)"))
    parsed = []
    actual = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(c, offline=True, lexical_only=True)
    assert parsed == ["src/b.py"], parsed
    oracle = dict(c, data=str(tmp_path / "oracle"))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, updated["version"]) == records(oracle, full["version"])
    assert old["version"] != updated["version"]
