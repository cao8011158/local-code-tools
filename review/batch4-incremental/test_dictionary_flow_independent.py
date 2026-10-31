"""Independent public-build controls for the bounded dictionary update slice."""
import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


A = "def first(): pass\ndef second(): pass\nregistry={'go':first}\nregistry['go']=second\n"
B = "from a import registry\nalias=registry\ndef run():\n    alias['go']()\n"


def fixture(tmp_path, noise=0):
    c, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/a.py').write_text(A)
    (repo / 'src/b.py').write_text(B)
    (repo / 'src/unrelated.py').write_text('def idle(): pass\n')
    for i in range(noise):
        (repo / f'src/noise_{i}.py').write_text(f'def idle_{i}(): pass\n')
    return c, repo


def records(c, version):
    folder, _ = manifest(c, version)
    result = {}
    for filename, tables in (
        ('catalog.sqlite', ('nodes', 'edges')),
        ('graph-sites.sqlite', ('sites', 'import_requests', 'import_dependencies', 'query_observations')),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                result[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                       for (raw,) in db.execute(f'select data from {table}'))
    return result


def assert_fresh_equal(c, version, tmp_path, suffix):
    oracle = dict(c, data=str(tmp_path / suffix))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, version) == records(oracle, full['version'])


@pytest.mark.parametrize('noise', [0, 20])
def test_dictionary_change_delete_and_failed_publish_reuse_unrelated(tmp_path, monkeypatch, noise):
    c, repo = fixture(tmp_path, noise)
    first = build(c, offline=True, lexical_only=True)
    original = records(c, first['version'])
    actual = extraction.python_nodes
    parsed = []

    def counted(file):
        parsed.append(file['path'])
        return actual(file)

    monkeypatch.setattr(extraction, 'python_nodes', counted)
    changed_text = A.replace("registry['go']=second", "registry['go']=first")
    (repo / 'src/a.py').write_text(changed_text)
    second = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py'], parsed
    assert records(c, first['version']) == original
    assert_fresh_equal(c, second['version'], tmp_path, 'oracle-change')
    # Removing the overriding registration must use old evidence and recompute B.
    (repo / 'src/a.py').write_text(changed_text.replace("registry['go']=first\n", ''))
    parsed.clear()
    with pytest.raises(ToolError, match='Injected interruption'):
        build(c, offline=True, lexical_only=True, fail_at='before_publish')
    assert current(c) == second['version']
    assert sorted(parsed) == ['src/a.py', 'src/b.py'], parsed
    parsed.clear()
    third = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py'], parsed
    assert_fresh_equal(c, third['version'], tmp_path, 'oracle-delete')


def test_missing_key_becomes_present_and_removed_again(tmp_path, monkeypatch):
    c, repo = fixture(tmp_path, 3)
    (repo / 'src/b.py').write_text(B.replace("['go']", "['new']"))
    build(c, offline=True, lexical_only=True)
    (repo / 'src/a.py').write_text(A + "registry['new']=second\n")
    changed = build(c, offline=True, lexical_only=True)
    assert changed['incremental']['analysis_scope']['mode'] != 'full-graph'
    assert_fresh_equal(c, changed['version'], tmp_path, 'oracle-present')
    (repo / 'src/a.py').write_text(A)
    removed = build(c, offline=True, lexical_only=True)
    assert removed['incremental']['analysis_scope']['mode'] != 'full-graph'
    assert_fresh_equal(c, removed['version'], tmp_path, 'oracle-absent')


@pytest.mark.parametrize('extra', [
    'def expose():\n    return registry\n',
    'def mutate(value):\n    value["go"]=second\nmutate(registry)\n',
    'registry.update({"go":second})\n',
    'registry[unknown_key]=second\n',
    'if condition:\n    registry["go"]=second\n',
])
def test_unproved_dictionary_effects_keep_full_fallback(tmp_path, extra):
    c, repo = fixture(tmp_path)
    build(c, offline=True, lexical_only=True)
    (repo / 'src/a.py').write_text(A + extra)
    changed = build(c, offline=True, lexical_only=True)
    assert changed['incremental']['analysis_scope']['mode'] == 'full-graph'
    assert_fresh_equal(c, changed['version'], tmp_path, 'oracle-unsafe')
