"""Check semantics before changing historical full-only admission expectations."""

import sqlite3

import pytest

from lct.storage import build, manifest
import test_dictionary_flow_independent as flow
import test_dictionary_local_independent as local
import test_mixed_dictionary_independent as mixed
from test_general_context_independent import semantic_tables


EFFECTS = [
    'def expose():\n    return registry\n',
    'def mutate(value):\n    value["go"]=second\nmutate(registry)\n',
    'registry.update({"go":second})\n',
    'registry[unknown_key]=second\n',
    'if condition:\n    registry["go"]=second\n',
]


@pytest.mark.parametrize('family,extra', [('cross', e) for e in EFFECTS] +
                         [('same', e) for e in EFFECTS] + [('caller', e) for e in [
                             'from a import registry\ndef invoke():\n    return registry\n',
                             'from missing_provider import run\ndef invoke():\n    run()\n',
                             'from b import missing_name\ndef invoke():\n    missing_name()\n']])
def test_previously_rejected_complex_owner_is_recomputed_with_full_semantics(tmp_path, family, extra):
    if family == 'cross':
        config, repo = flow.fixture(tmp_path)
        path, new_source, selected, retained = 'a.py', flow.A + extra, {'src/a.py', 'src/b.py'}, 1
    elif family == 'same':
        config, repo = local.fixture(tmp_path, 2)
        path, new_source, selected, retained = 'registry.py', local.SOURCE + extra, {'src/registry.py'}, 3
    else:
        config, repo = mixed.make(tmp_path, 2)
        path, new_source, selected, retained = 'c.py', extra, {
            'src/a.py', 'src/b.py', 'src/c.py', 'src/spare.py'}, 2
    previous = build(config, offline=True, lexical_only=True)
    old = semantic_tables(config, previous['version'])
    (repo / 'src' / path).write_text(new_source)
    changed = build(config, offline=True, lexical_only=True)
    scope = changed['incremental']['analysis_scope']
    assert scope['mode'] == 'general-passive-component', scope
    assert {p for _, p in scope['selected_keys']} == selected, scope
    assert scope['reused_python_files'] == retained
    assert semantic_tables(config, previous['version']) == old
    oracle_config = dict(config, data=str(tmp_path / 'fresh'))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert semantic_tables(config, changed['version']) == semantic_tables(oracle_config, oracle['version'])
    assert oracle['simple_python_certificate'] is None
    assert changed['simple_python_certificate'] == oracle['simple_python_certificate']
    assert changed['value_flow_coverage'] == oracle['value_flow_coverage'] == 'partial'
    folder, _ = manifest(config, changed['version'])
    with sqlite3.connect(folder / 'graph-sites.sqlite') as database:
        assert database.execute('select count(*) from simple_python_certificates').fetchone() == (0,)
