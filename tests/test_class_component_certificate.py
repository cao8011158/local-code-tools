"""The bounded class gate and event identity use only relevant syntax."""

import ast
import json
import sqlite3

import pytest

from lct.python_effects import EffectCatalog
from lct.simple_python import CERTIFICATE, certify
from lct.storage import build, manifest
from tests.synthetic_support import initialize


def certificate(source):
    return certify(
        [dict(repository="r", path="a.py")],
        {"r:a.py:module:a#1": ast.parse(source)},
    )


@pytest.mark.parametrize("source", [
    "def f(value):\n    return value.cb\n",
    "def f(value):\n    alias = value\n    return alias.cb\n",
    "def f():\n    obj = make()\n    obj.__dict__\n",
    "class Box:\n    def __getattr__(self, name): pass\n",
    "class Box:\n    def run(self): self.cb = f\n",
    "class Box(Base): pass\n",
    "class Box:\n    cb = f\n",
    "def f():\n    Box.cb = other\n",
    "def f():\n    return getattr(Box(), 'cb')\n",
])
def test_uncertified_class_or_dynamic_receiver(source):
    assert certificate(source) is None


def test_explicit_constructor_method_and_docstrings():
    assert certificate('''"""Module."""
def first(): pass
class Box:
    """Instance."""
    def __init__(self):
        """Construct."""
        self.cb = first
    def invoke(self):
        self.cb()
def factory():
    return Box()
def use():
    value = factory()
    saved = value.invoke
    saved()
    factory().cb()
''') == CERTIFICATE


def test_effect_event_ids_ignore_shared_markers_and_unrelated_module_order():
    def make(reverse):
        target = ast.parse("def use():\n x = f()\n y = x + 1\n x.cb()\n")
        other = ast.parse("def unrelated():\n x = f()\n y = x + 1\n")
        use, unrelated = target.body[0], other.body[0]
        trees = {"use": use, "unrelated": unrelated}
        if reverse:
            trees = dict(reversed(list(trees.items())))
        ownership = {}
        for scope, tree in trees.items():
            for node in ast.walk(tree):
                ownership[id(node)] = (scope, "body")
        catalog = EffectCatalog(trees, ownership)
        ids = [event.ident for event in catalog.by_scope["use"]]
        before = [event.ident for event in catalog.before("use", use.body[-1].value)]
        return ids, before

    assert make(False) == make(True)


def test_returned_instance_attribute_call_matches_full_catalog(tmp_path):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    owner = repo / "src/a.py"
    owner.write_text(
        "def first(): pass\ndef second(): pass\n"
        "class Box:\n"
        "    def __init__(self): self.cb = first\n"
        "def factory(): return Box()\n")
    (repo / "src/b.py").write_text("from a import factory\ndef use(): factory().cb()\n")
    build(config, offline=True, lexical_only=True)
    owner.write_text(owner.read_text().replace("self.cb = first", "self.cb = second"))
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["python_files_parsed"] == 2
    oracle = build(dict(config, data=str(tmp_path / "oracle")), offline=True, lexical_only=True)

    def all_records(settings, version):
        folder, _ = manifest(settings, version)
        output = {}
        for database, tables in (
            ("catalog.sqlite", ("nodes", "edges")),
            ("graph-sites.sqlite", ("sites", "query_observations",
                                    "import_dependencies", "import_requests")),
        ):
            with sqlite3.connect(folder / database) as db:
                for table in tables:
                    output[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                           for row in db.execute(f"select data from {table}"))
        return output

    assert all_records(config, updated["version"]) == all_records(
        dict(config, data=str(tmp_path / "oracle")), oracle["version"])
