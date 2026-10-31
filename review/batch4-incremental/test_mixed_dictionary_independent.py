"""Independent public updates through ordinary callers of dictionary readers."""
import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


A = "def first(): pass\ndef second(): pass\nregistry={'go':first}\nregistry['go']=first\n"
B = "from a import registry\ndef run():\n    registry['go']()\n"
C = "from b import run\ndef invoke():\n    run()\n"


def make(tmp_path, noise=0, extra_caller=False):
    c, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    for name, source in [('a', A), ('b', B), ('c', C)]:
        (repo / f'src/{name}.py').write_text(source)
    (repo / 'src/spare.py').write_text('def idle(): pass\nspare={"go":idle}\n')
    for i in range(noise):
        (repo / f'src/noise_{i}.py').write_text(f'def idle_{i}(): pass\n')
    if extra_caller:
        (repo / 'src/d.py').write_text('from c import invoke\ndef main():\n    invoke()\n')
    return c, repo


def contents(c, version):
    folder, _ = manifest(c, version)
    data = {}
    for filename, tables in [('catalog.sqlite', ('nodes', 'edges')),
            ('graph-sites.sqlite', ('sites', 'import_requests', 'import_dependencies',
                                    'query_observations', 'value_nodes'))]:
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                data[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                     for row in db.execute(f'select data from {table}'))
    with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
        for table in ('value_edges', 'value_reads'):
            data[table] = sorted(db.execute(f'select * from {table}'))
    return data


def fresh_equal(c, version, tmp_path, name):
    full_config = dict(c, data=str(tmp_path / name))
    oracle = build(full_config, offline=True, lexical_only=True)
    assert contents(c, version) == contents(full_config, oracle['version'])


@pytest.mark.parametrize('noise', [0, 20])
def test_plain_caller_target_change_removal_and_failed_publish(tmp_path, monkeypatch, noise):
    c, repo = make(tmp_path, noise)
    first = build(c, offline=True, lexical_only=True)
    prior = contents(c, first['version'])
    parsed = []
    actual = extraction.python_nodes
    def counted(file):
        parsed.append(file['path'])
        return actual(file)
    monkeypatch.setattr(extraction, 'python_nodes', counted)
    changed_source = A.replace("registry['go']=first", "registry['go']=second")
    assert changed_source != A
    (repo / 'src/a.py').write_text(changed_source)
    second = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py', 'src/c.py'], parsed
    assert contents(c, first['version']) == prior
    fresh_equal(c, second['version'], tmp_path, 'oracle-changed')
    (repo / 'src/a.py').write_text(changed_source.replace("registry['go']=second\n", ''))
    parsed.clear()
    with pytest.raises(ToolError, match='Injected interruption'):
        build(c, offline=True, lexical_only=True, fail_at='before_publish')
    assert current(c) == second['version']
    assert sorted(parsed) == ['src/a.py', 'src/b.py', 'src/c.py']
    parsed.clear()
    retried = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py', 'src/c.py']
    fresh_equal(c, retried['version'], tmp_path, 'oracle-removed')
    print(json.dumps({'noise': noise, 'parsed_update': ['src/a.py', 'src/b.py', 'src/c.py'],
                      'unrelated_sources': noise + 1}, sort_keys=True))


def test_new_key_with_two_plain_caller_hops(tmp_path, monkeypatch):
    c, repo = make(tmp_path, 4, extra_caller=True)
    (repo / 'src/b.py').write_text(B.replace("['go']", "['new']"))
    build(c, offline=True, lexical_only=True)
    parsed = []
    actual = extraction.python_nodes
    monkeypatch.setattr(extraction, 'python_nodes', lambda f: (parsed.append(f['path']), actual(f))[1])
    (repo / 'src/a.py').write_text(A + "registry['new']=second\n")
    updated = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py', 'src/c.py', 'src/d.py'], parsed
    fresh_equal(c, updated['version'], tmp_path, 'oracle-new-key')


@pytest.mark.parametrize('source', [
    'from a import registry\ndef invoke():\n    return registry\n',
    'from missing_provider import run\ndef invoke():\n    run()\n',
    'from b import missing_name\ndef invoke():\n    missing_name()\n',
])
def test_context_does_not_admit_registry_escape_or_missing_exports(tmp_path, source):
    c, repo = make(tmp_path, 2)
    build(c, offline=True, lexical_only=True)
    (repo / 'src/c.py').write_text(source)
    updated = build(c, offline=True, lexical_only=True)
    assert updated['incremental']['analysis_scope']['mode'] == 'full-graph'
    fresh_equal(c, updated['version'], tmp_path, 'oracle-rejected')
