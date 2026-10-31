"""Independent accepted-slice controls; original cross-file probe is separate."""
import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


SOURCE = "def first(): pass\ndef second(): pass\nregistry={'go':first}\nregistry['go']=second\ndef run():\n    registry['go']()\n"


def fixture(tmp_path, noise):
    c, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/registry.py').write_text(SOURCE)
    (repo / 'src/unrelated.py').write_text('def idle(): pass\n')
    for i in range(noise):
        (repo / f'src/noise_{i}.py').write_text(f'def idle_{i}(): pass\n')
    return c, repo


def records(c, version):
    folder, _ = manifest(c, version)
    data = {}
    for filename, tables in (
        ('catalog.sqlite', ('nodes', 'edges')),
        ('graph-sites.sqlite', ('sites', 'import_requests', 'import_dependencies', 'query_observations')),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                data[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                     for (raw,) in db.execute(f'select data from {table}'))
    return data


def fresh_equal(c, version, tmp_path, name):
    oracle = dict(c, data=str(tmp_path / name))
    full = build(oracle, offline=True, lexical_only=True)
    assert records(c, version) == records(oracle, full['version'])


@pytest.mark.parametrize('noise', [0, 20])
def test_same_file_writer_change_delete_failure_then_identical(tmp_path, monkeypatch, noise):
    c, repo = fixture(tmp_path, noise)
    old = build(c, offline=True, lexical_only=True)
    old_records = records(c, old['version'])
    parsed = []
    actual = extraction.python_nodes

    def counted(file):
        parsed.append(file['path'])
        return actual(file)

    monkeypatch.setattr(extraction, 'python_nodes', counted)
    changed_source = SOURCE.replace("registry['go']=second", "registry['go']=first")
    (repo / 'src/registry.py').write_text(changed_source)
    changed = build(c, offline=True, lexical_only=True)
    assert parsed == ['src/registry.py'], parsed
    assert records(c, old['version']) == old_records
    fresh_equal(c, changed['version'], tmp_path, 'oracle-change')
    (repo / 'src/registry.py').write_text(changed_source.replace("registry['go']=first\n", ''))
    parsed.clear()
    with pytest.raises(ToolError, match='Injected interruption'):
        build(c, offline=True, lexical_only=True, fail_at='before_publish')
    assert current(c) == changed['version']
    assert parsed == ['src/registry.py'], parsed
    parsed.clear()
    retried = build(c, offline=True, lexical_only=True)
    assert parsed == ['src/registry.py'], parsed
    fresh_equal(c, retried['version'], tmp_path, 'oracle-delete')
    parsed.clear()
    identical = build(c, offline=True, lexical_only=True)
    assert parsed == []
    assert identical['incremental']['analysis_scope']['mode'] == 'identical-python-capture-reuse'
    assert records(c, retried['version']) == records(c, identical['version'])


@pytest.mark.parametrize('extra', [
    'def expose():\n    return registry\n',
    'def mutate(value):\n    value["go"]=second\nmutate(registry)\n',
    'registry.update({"go":second})\n',
    'registry[unknown_key]=second\n',
    'if condition:\n    registry["go"]=second\n',
])
def test_new_unproved_effects_are_not_admitted(tmp_path, extra):
    c, repo = fixture(tmp_path, 2)
    build(c, offline=True, lexical_only=True)
    (repo / 'src/registry.py').write_text(SOURCE + extra)
    changed = build(c, offline=True, lexical_only=True)
    assert changed['incremental']['analysis_scope']['mode'] == 'full-graph'
    fresh_equal(c, changed['version'], tmp_path, 'oracle-unsupported')
