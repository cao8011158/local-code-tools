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
        path, new_source = 'a.py', flow.A + extra
    elif family == 'same':
        config, repo = local.fixture(tmp_path, 2)
        path, new_source = 'registry.py', local.SOURCE + extra
    else:
        config, repo = mixed.make(tmp_path, 2)
        path, new_source = 'c.py', extra
    previous = build(config, offline=True, lexical_only=True)
    old = semantic_tables(config, previous['version'])
    (repo / 'src' / path).write_text(new_source)
    changed = build(config, offline=True, lexical_only=True)
    scope = changed['incremental']['analysis_scope']
    owner_update = family == 'caller' or extra.startswith('if condition:')
    assert scope['mode'] == ('incremental-owners' if owner_update else 'full-graph'), scope
    if owner_update:
        assert {p for _, p in scope['selected_keys']} == {'src/' + path}
        assert scope['reused_python_files'] == (5 if family == 'caller' else (2 if family == 'cross' else 3))
    else:
        assert scope['reason'] in {'python-owner-membership-changed',
                                   'changed-opaque-call-effect-unavailable',
                                   'unbounded-changed-writer-input'}
        assert scope.get('reused_python_files', 0) == 0
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
