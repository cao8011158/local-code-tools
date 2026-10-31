"""Actual internal graph traversal, reverse consumers and unrelated producers."""
import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


A = ('def first(): pass\ndef second(): pass\n'
     'registry={"go":first}\nregistry["go"]=second\n'
     'other={"go":first}\n')
B = ('from a import registry, other\nalias=registry\n'
     'def run():\n    alias["go"]()\n    other["go"]()\n')


def make(tmp_path, noise):
    c, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/a.py').write_text(A)
    (repo / 'src/b.py').write_text(B)
    (repo / 'src/idle.py').write_text('def idle(): pass\n')
    for i in range(noise):
        (repo / f'src/spare_{i}.py').write_text(f'def idle_{i}(): pass\nspare_{i}={{"go":idle_{i}}}\n')
    return c, repo


def contents(c, version):
    folder, _ = manifest(c, version)
    data = {}
    with sqlite3.connect(folder / 'catalog.sqlite') as db:
        for table in ('nodes', 'edges'):
            data[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                 for row in db.execute(f'select data from {table}'))
    with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
        for table in ('sites', 'import_requests', 'import_dependencies', 'query_observations', 'value_nodes'):
            data[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                 for row in db.execute(f'select data from {table}'))
        for table in ('value_edges', 'value_reads'):
            data[table] = sorted(db.execute(f'select * from {table}'))
    return data


@pytest.mark.parametrize('noise', [0, 20])
def test_actual_reverse_queries_and_unrelated_producer_retention(tmp_path, monkeypatch, noise):
    c, repo = make(tmp_path, noise)
    first = build(c, offline=True, lexical_only=True)
    folder, meta = manifest(c, first['version'])
    assert meta['value_flow_projection'] == 'internal-sqlite-only'
    with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
        raw = [json.loads(row[0]) for row in db.execute('select data from value_nodes')]
    containers = {n['id']: n for n in raw if n['kind'] == 'container'}
    a_entries = [n for n in raw if n['kind'] == 'entry' and containers[n['container']]['name'] in {'registry', 'other'}]
    assert len(a_entries) == 2
    assert len({n['container'] for n in a_entries}) == 2
    assert all(n['key'] == 'go' and n['present'] is True for n in a_entries)
    reads = [n for n in raw if n['kind'] == 'read']
    assert len(reads) == 2  # aliases do not create a second dictionary
    with FileDependencies(folder, meta) as deps:
        for entry in a_entries:
            assert deps.value_readers(entry['id']) == {('synthetic-review', 'src/b.py')}
        for read in reads:
            page = deps.get_value_relations(read['id'])
            assert page['has_more'] is False
            assert {'READS', 'POSSIBLE_CALLS'} <= {r['kind'] for r in page['relations']}
        small = deps.get_value_relations(reads[0]['id'], limit=1)
        assert small['has_more'] is True and len(small['relations']) == 1
        assert deps.get_value_nodes([a_entries[0]['id']])[0]['id'] == a_entries[0]['id']
        with pytest.raises(ToolError):
            deps.get_value_nodes(['x'] * 101)

    actual = extraction.python_nodes
    parsed = []
    monkeypatch.setattr(extraction, 'python_nodes', lambda f: (parsed.append(f['path']), actual(f))[1])
    original = FileDependencies.value_readers
    watcher = FileDependencies.analysis_watchers
    lookups, watcher_calls = [], []

    def measured(self, entry):
        sql = []; vm = [0]
        self.db.set_trace_callback(sql.append)
        def tick():
            vm[0] += 1
            return 0
        self.db.set_progress_handler(tick, 1)
        try:
            rows = original(self, entry)
        finally:
            self.db.set_trace_callback(None)
            self.db.set_progress_handler(None, 0)
        plans = [r[3] for query in sql for r in self.db.execute('explain query plan ' + query)]
        assert plans and all('SEARCH' in p and 'SCAN' not in p for p in plans)
        lookups.append(dict(rows=len(rows), vm=vm[0], queries=len(sql), plans=plans))
        return rows

    def watched(self, kind):
        watcher_calls.append(kind)
        return watcher(self, kind)

    monkeypatch.setattr(FileDependencies, 'value_readers', measured)
    monkeypatch.setattr(FileDependencies, 'analysis_watchers', watched)
    changed_source = A.replace('registry["go"]=second', 'registry["go"]=first')
    assert changed_source != A
    (repo / 'src/a.py').write_text(changed_source)
    changed = build(c, offline=True, lexical_only=True)
    assert sorted(parsed) == ['src/a.py', 'src/b.py'], parsed
    assert lookups, 'Reverse index must be consumed by the public update path'
    assert watcher_calls == ['slot-writer-universe'], watcher_calls
    got = contents(c, changed['version'])
    oracle = dict(c, data=str(tmp_path / 'oracle'))
    full = build(oracle, offline=True, lexical_only=True)
    assert got == contents(oracle, full['version'])
    print(json.dumps(dict(noise=noise, queries=lookups, parsed_update=['src/a.py', 'src/b.py']), sort_keys=True))
