"""Actual public-build requester lookups remain indexed under unrelated growth."""

import json

import lct.extract as extraction
from lct.storage import FileDependencies, build
from tests.test_cross_repository_python_incremental import fixture, same_as_full


def test_shadow_update_uses_requester_index(tmp_path, monkeypatch):
    parse = extraction.python_nodes
    active, evidence = {}, []

    def traced(method, label, self, *args):
        if not active:
            return method(self, *args)
        statements, ticks = [], [0]
        self.db.set_trace_callback(statements.append)
        def tick():
            ticks[0] += 1
            return 0
        self.db.set_progress_handler(tick, 1)
        try:
            result = method(self, *args)
        finally:
            self.db.set_trace_callback(None)
            self.db.set_progress_handler(None, 0)
        plans = [row[3] for sql in statements if sql.lower().startswith('select')
                 for row in self.db.execute('explain query plan ' + sql)]
        searches = [p for p in plans if p.startswith('SEARCH ')]
        assert searches and not any('SCAN ' in p for p in plans), plans
        assert all('import_lookup_requester' in p for p in searches), plans
        assert all(p.startswith('SEARCH ') or p.startswith('CORRELATED SCALAR SUBQUERY')
                   for p in plans), plans
        rows = int(result) if isinstance(result, bool) else len(result)
        active['queries'].append(dict(method=label, target=args, rows=rows, vm_steps=ticks[0], plans=plans))
        return result

    def counted(file):
        if active:
            active['parsed'].append((file['repository'], file['path']))
        return parse(file)

    def wrap(method, label):
        return lambda self, *args: traced(method, label, self, *args)
    for label in ('requesters', 'has_descendant_requesters'):
        monkeypatch.setattr(FileDependencies, label, wrap(getattr(FileDependencies, label), label))
    monkeypatch.setattr(extraction, 'python_nodes', counted)
    for noise in (0, 20):
        case = tmp_path / str(noise)
        config, consumer, provider = fixture(case, pinned=True)
        (consumer / 'src/caller.py').write_text(
            'from dnd5e_engine.evaluation import target\ndef run(): target()\n')
        for i in range(noise):
            (consumer / 'src' / f'leaf_{i}.py').write_text('def work(): pass\n')
            (consumer / 'src' / f'caller_{i}.py').write_text(
                f'from leaf_{i} import work\ndef run(): work()\n')
        build(config, offline=True, lexical_only=True)
        own = consumer / 'src/dnd5e_engine/evaluation.py'
        own.parent.mkdir(exist_ok=True)
        own.write_text('def target(): pass\n')
        active.update(queries=[], parsed=[])
        updated = build(config, offline=True, lexical_only=True)
        assert updated['incremental']['analysis_scope']['mode'] == 'certified-simple-python-component'
        assert set(active['parsed']) == {
            ('synthetic-review', 'src/caller.py'),
            ('synthetic-review', 'src/dnd5e_engine/evaluation.py'),
            ('trpg-rules-engine', 'src/dnd5e_engine/evaluation.py'),
        }
        evidence.append(dict(noise=noise, **active))
        active.clear()
        same_as_full(config, updated, case)
    shape = lambda x: sorted((q['method'], q['target'], q['rows']) for q in x['queries'])
    assert shape(evidence[0]) == shape(evidence[1])
    assert sum(q['rows'] for q in evidence[0]['queries']) == 1
    print(json.dumps(evidence, sort_keys=True))
