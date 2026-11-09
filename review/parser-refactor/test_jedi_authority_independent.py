"""Independent acceptance of the user's Jedi-only target authority contract."""

import json
import sqlite3
from unittest.mock import patch

import pytest

from lct.python_analysis import Analyzer
from lct.storage import build, current, manifest
from lct.common import ToolError
from tests.synthetic_support import forbid_provider, initialize
from tests.test_python_pipeline import analyze, site


HEADER_SOURCE = '''def first(): pass
def second(): pass
def third(): pass
handlers = {'go': first}
old = handlers
def sentinel(x=(handlers := {'go': second})):
    pass
handlers['go'] = third
def run():
    old['go']()
'''


def test_definition_header_cannot_override_correct_jedi_target(tmp_path):
    result = analyze(tmp_path, {'demo.py': HEADER_SOURCE}, closed=False)
    observed = site(result, "old['go']", 'run')
    raw = [record for item in observed['evidence'] if item.get('tool') == 'jedi'
           for record in item.get('raw', [])]
    assert any(record.get('name') == 'first' for record in raw)
    assert observed['names'] == {'first'}
    assert not any('third' in target for target in observed['targets'])


def test_call_sites_enter_jedi_bridge_once_with_separate_execution_count(tmp_path):
    from collections import Counter

    entries = Counter()
    original = Analyzer.query

    def observed(self, scope, expr, goto=False, signature=False):
        if signature:
            entries[self.module_for[scope], expr.lineno, expr.col_offset] += 1
        return original(self, scope, expr, goto=goto, signature=signature)

    with patch.object(Analyzer, 'query', observed):
        result = analyze(tmp_path, {'demo.py': HEADER_SOURCE}, closed=False)
    assert entries and set(entries.values()) == {1}
    info = result[2]
    assert info['candidate_site_queries_prepared'] == 0
    assert info['jedi_query_entries'] >= sum(entries.values())
    assert info['jedi_queries_executed'] <= info['jedi_query_entries']
    assert site(result, "old['go']", 'run')['names'] == {'first'}


def test_definition_header_keeps_allocation_sources_separate_from_targets(tmp_path):
    result = analyze(tmp_path, {'demo.py': HEADER_SOURCE}, closed=False)
    allocations = {row['origin'] for row in result[2].get('_unit_writes', [])
                   if row['kind'] in {'dictionary-literal', 'definition-default-dictionary'}}
    assert len(allocations) == 2, 'definition-time allocation source was silently lost'
    assert site(result, "old['go']", 'run')['names'] == {'first'}


def test_context_entry_without_tool_target_retains_explicit_site_evidence(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'from contextlib import contextmanager\n'
                     '@contextmanager\ndef manager():yield 1\n'
                     'def run():\n with manager():pass\n'}, closed=False)
    entries = [edge for edge in result[1] if edge['kind'] == 'CONTEXT_ENTERS']
    assert entries, 'context entry was silently removed with the legacy solver'
    assert all(edge.get('unknown_origin') or edge.get('target') for edge in entries)
    assert all(edge['line'] == 5 for edge in entries)


@pytest.mark.parametrize('source', [
    'def first(): pass\nalias=first\ndef run():alias()\n',
    'def first(): pass\ndef execute(cb):cb()\ndef run():execute(first)\n',
    'def first(): pass\ndef getter():return first\ndef run():getter()()\n',
    'class Base:\n def leaf(self):pass\nclass Child(Base):pass\ndef run():Child().leaf()\n',
    'def first():pass\nhandlers={"go":first}\ndef run():handlers["go"]()\n',
    'def deco(fn):return fn\n@deco\ndef run():pass\nrun()\n',
    'from contextlib import contextmanager\n@contextmanager\ndef manager():yield 1\n'
    'def run():\n with manager():pass\n',
])
def test_public_build_never_enters_legacy_target_solver(tmp_path, source):
    def denied(*args, **kwargs):
        raise AssertionError('removed LCT target solver entered production')
    with patch.object(Analyzer, 'resolve', denied, create=True), \
         patch.object(Analyzer, '_resolve', denied, create=True), \
         patch.object(Analyzer, 'adjudicate', denied, create=True), \
         patch.object(Analyzer, 'tool_first_lexical', denied, create=True), \
         patch.object(Analyzer, 'tool_first_subscript', denied, create=True):
        result = analyze(tmp_path, {'demo.py': source}, closed=False)
    assert result[2]['sites']


def test_legacy_target_engine_is_removed_from_analyzer():
    assert not {'resolve', '_resolve', 'adjudicate', 'caller_atoms', 'parameter',
                'container_slots', 'instance_field', 'field_event', 'registry_arguments',
                '_build_query_certificates', '_direct_lexical_query', 'reusable_queries'
                }.intersection(Analyzer.__dict__)


def test_empty_jedi_observation_is_not_filled_by_source_records(tmp_path):
    from lct import python_analysis
    original = python_analysis.jedi.Script

    def empty(*args, **kwargs):
        script = original(*args, **kwargs)
        script.infer = lambda *args, **kwargs: []
        script.get_signatures = lambda *args, **kwargs: []
        return script

    source = ('def first():pass\nhandlers={"go":first}\nalias=first\n'
              'def run():\n alias()\n handlers["go"]()\n')
    with patch.object(python_analysis.jedi, 'Script', empty):
        result = analyze(tmp_path, {'demo.py': source})
    for expr in ('alias', "handlers['go']"):
        observed = site(result, expr, 'run')
        assert observed['targets'] == []
        assert observed['unknown_origin'] and not observed['complete']
        assert any('no-result' in reason for reason in observed['unresolved_reasons'])


def test_query_error_is_preserved_without_source_fallback(tmp_path):
    from lct import python_analysis
    original = python_analysis.jedi.Script

    def fail(*args, **kwargs):
        script = original(*args, **kwargs)
        def error(*args, **kwargs):
            raise RuntimeError('independent injected Jedi error')
        script.infer = error
        script.get_signatures = error
        return script

    with patch.object(python_analysis.jedi, 'Script', fail):
        result = analyze(tmp_path, {'demo.py': 'def first():pass\ndef run():first()\n'})
    observed = site(result, 'first', 'run')
    assert observed['targets'] == [] and observed['unknown_origin']
    assert 'jedi-error:RuntimeError' in observed['unresolved_reasons']


def test_multiple_jedi_targets_survive_without_custom_selection(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def first():pass\ndef second():pass\n'
                     'if flag:fn=first\nelse:fn=second\ndef run():fn()\n'})
    assert site(result, 'fn', 'run')['names'] == {'first', 'second'}


@pytest.mark.parametrize('source,expression', [
    ('def forward(*args,**kwargs):\n return forward(*args,**kwargs)\nforward(1)\n', 'forward'),
    ('def first(*args,**kwargs):\n return second(*args,**kwargs)\n'
     'def second(*args,**kwargs):\n return first(*args,**kwargs)\nfirst(1)\n', 'first'),
])
def test_real_jedi_lazy_parameter_error_keeps_correct_target(tmp_path, source, expression):
    # Jedi 0.20.1 returns the correct signature, then params recursively expands
    # forwarding stars. Original API reproduction is retained separately.
    result = analyze(tmp_path, {'demo.py': source}, closed=False)
    observed = site(result, expression, 'demo')
    assert observed['names'] == {expression}
    raw = [record for evidence in observed['evidence'] if evidence.get('tool') == 'jedi'
           for record in evidence.get('raw', [])]
    assert any(row.get('parameters_error') == 'RecursionError' for row in raw)
    assert any(row[2] == 'unresolved-argument-source'
               for row in result[2].get('_unit_analysis_watches', []))


def test_registered_callback_tool_gap_stays_unknown(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def first():pass\n'
                     'def execute(callback):callback()\nR={}\n'
                     'def register(key,fn):R[key]=fn\nregister("go",execute)\n'
                     'def run():R["go"](first)\n'}, closed=False)
    for expression, owner in (("R['go']", 'run'), ('callback', 'execute')):
        observed = site(result, expression, owner)
        assert observed['targets'] == []
        assert observed['unknown_origin'] and not observed['complete']


def test_statement_mapping_preserves_mapping_gap_without_solving_rhs(tmp_path):
    from types import SimpleNamespace
    from lct.extract import python_nodes
    from lct.graph import Graph
    from lct.common import digest
    source = 'def first():pass\nalias=first\ndef run():alias()\n'
    nodes, trees = python_nodes(dict(repository='fixture', path='demo.py', text=source,
                                     is_test=False, sha256=digest(source)))
    graph = Graph(nodes, trees, [dict(name='fixture', path=str(tmp_path),
                                     head='captured', status='', closed_world=False)])
    analyzer = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    try:
        module = next(ident for ident, node in graph.nodes.items() if node['kind'] == 'module')
        path = next(path for path, ident in analyzer.paths.items() if ident == module)
        name = SimpleNamespace(name='alias', type='statement', full_name='demo.alias',
                               line=2, column=0, module_path=path)
        result, raw = analyzer.map_name(name)
        assert not any(atom.kind in {'callable', 'class'} for atom in result.atoms)
        assert result.unknown
        assert 'unmapped' in raw['mapping'] or 'unsupported' in raw['mapping']
    finally:
        analyzer.close()


def test_call_specific_jedi_api_resolves_classmethod_without_lexical_solver(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'class C:\n @classmethod\n'
                     ' def build(cls):pass\ndef run():C.build()\n'}, closed=False)
    observed = site(result, 'C.build', 'run')
    assert observed['names'] == {'C.build'}


@pytest.mark.parametrize('definition', ['class C:pass', 'class C:\n def __call__(self):pass'])
def test_inferred_instance_is_not_reported_as_constructor_call(tmp_path, definition):
    result = analyze(tmp_path, {'demo.py': definition+'\nc=C()\ndef run():c()\n'}, closed=False)
    observed = site(result, 'c', 'run')
    assert 'C' not in observed['names'], 'an instance type was changed into a constructor target'


def test_call_specific_query_position_handles_utf8_and_split_call(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def 目标():pass\ndef run():\n'
                     ' (目标) \\\n'
                     '  ()\n'}, closed=False)
    assert site(result, '目标', 'run')['names'] == {'目标'}


def _read(config, version, expression):
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
        return next(record for raw, in db.execute('select data from sites')
                    for record in [json.loads(raw)] if record['expression'] == expression)


def test_public_local_updates_requery_and_preserve_old_view(tmp_path):
    config, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    config['retained_versions'] = 8
    provider = repo / 'src/provider.py'
    (repo / 'src/client.py').write_text('from provider import handlers\n'
                                      'def run():handlers["go"]()\n')
    (repo / 'src/idle.py').write_text('def unrelated():return 1\n')
    versions, first_view = [], None
    for value in ('first', 'second', None, 'first'):
        provider.write_text('def first():pass\ndef second():pass\n'
                            + ('handlers={}\n' if value is None else
                               f'handlers={{"go":{value}}}\n'))
        with forbid_provider():
            result = build(config, offline=True, lexical_only=True)
        observed = _read(config, result['version'], "handlers['go']")
        if value is None:
            assert not observed['targets'] and observed['unknown_origin']
        else:
            assert len(observed['targets']) == 1
            assert f':function:{value}#' in observed['targets'][0]
        if versions:
            scope = result['incremental']['analysis_scope']
            assert scope['mode'] == 'incremental-owners'
            assert not any(':function:unrelated#' in owner
                           for owner in scope['selected_owner_ids'])
        else:
            first_view = observed
        versions.append(result['version'])
        assert _read(config, versions[0], "handlers['go']") == first_view
    provider.write_text('def first():pass\ndef second():pass\nhandlers={"go":second}\n')
    with forbid_provider(), pytest.raises(ToolError, match='Injected'):
        build(config, offline=True, lexical_only=True, fail_at='before_publish')
    assert current(config) == versions[-1]
    assert _read(config, versions[0], "handlers['go']") == first_view


def test_new_changed_deleted_writer_keeps_negative_read_subscription(tmp_path):
    config, repo = initialize(tmp_path / 'writer-fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    config['retained_versions'] = 8
    (repo / 'src/provider.py').write_text('def first():pass\ndef second():pass\nhandlers={}\n')
    (repo / 'src/client.py').write_text('from provider import handlers\n'
                                      'def run():handlers["go"]()\n')
    (repo / 'src/idle.py').write_text('def unrelated():return 1\n')
    writer = repo / 'src/writer.py'
    old, old_view = None, None
    for value in (None, 'first', 'second', None):
        if value is not None:
            writer.write_text('from provider import handlers, first, second\n'
                              f'handlers["go"]={value}\n')
        elif writer.exists():
            writer.unlink()
        with forbid_provider():
            result = build(config, offline=True, lexical_only=True)
        observed = _read(config, result['version'], "handlers['go']")
        if old is None:
            old, old_view = result['version'], observed
        else:
            scope = result['incremental']['analysis_scope']
            assert scope['mode'] == 'incremental-owners'
            assert any(':function:run#' in owner for owner in scope['selected_owner_ids'])
            assert not any(':function:unrelated#' in owner for owner in scope['selected_owner_ids'])
        # This tests scheduling even when Jedi cannot infer a registered value.
        fresh_config = dict(config, data=str(tmp_path / f'fresh-{value}-{result["version"]}'))
        with forbid_provider():
            fresh = build(fresh_config, offline=True, lexical_only=True)
        oracle = _read(fresh_config, fresh['version'], "handlers['go']")
        assert observed['targets'] == oracle['targets']
        assert observed['unresolved_reasons'] == oracle['unresolved_reasons']
        assert _read(config, old, "handlers['go']") == old_view


@pytest.mark.parametrize('worker,import_name,consumer', [
    ('def execute(callback):callback()\n', 'execute', 'execute'),
    ('class Execute:\n def __init__(self,callback):callback()\n', 'Execute', 'Execute.__init__'),
])
def test_changed_callback_argument_selects_actual_consumer_function(
        tmp_path, worker, import_name, consumer):
    config, repo = initialize(tmp_path / 'callback-fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/worker.py').write_text(worker + 'def unrelated():return 1\n')
    caller = repo / 'src/caller.py'
    for value in ('first', 'second'):
        caller.write_text(f'from worker import {import_name}\ndef first():pass\ndef second():pass\n'
                          f'def run():{import_name}({value})\n')
        with forbid_provider():
            result = build(config, offline=True, lexical_only=True)
        if value == 'second':
            scope = result['incremental']['analysis_scope']
            assert scope['mode'] == 'incremental-owners'
            assert any(f':function:{consumer}#' in owner for owner in scope['selected_owner_ids'])
            assert not any(':function:unrelated#' in owner for owner in scope['selected_owner_ids'])
            fresh_config = dict(config, data=str(tmp_path / 'callback-fresh'))
            with forbid_provider():
                fresh = build(fresh_config, offline=True, lexical_only=True)
            observed = _read(config, result['version'], 'callback')
            oracle = _read(fresh_config, fresh['version'], 'callback')
            assert observed['targets'] == oracle['targets']
            assert observed['unresolved_reasons'] == oracle['unresolved_reasons']


@pytest.mark.parametrize('imports,expression', [
    ('from provider import handlers\n', 'handlers'),
    ('import provider\n', 'provider.handlers'),
])
def test_negative_container_read_and_write_keep_source_records(tmp_path, imports, expression):
    result = analyze(tmp_path, {
        'provider.py': 'def first():pass\nhandlers={}\n',
        'reader.py': imports + f'def run():{expression}["go"]()\n',
        'writer.py': imports + f'def write():{expression}["go"]=42\n',
    }, closed=False)
    by_id = {node['node_id']: node for node in result[0]}
    subscriptions = [row for row in result[2].get('_unit_subscriptions', [])
                     if by_id[row['consumer_owner']]['qualname'] == 'run']
    writes = [row for row in result[2].get('_unit_writes', [])
              if by_id[row['producer_owner']]['qualname'] == 'write']
    assert subscriptions, 'unresolved key lost its negative source subscription'
    assert writes, 'source writer was lost when target inference was removed'
    assert {row['origin'] for row in subscriptions} & {row['origin'] for row in writes}
    # The stored value is deliberately noncallable: provenance is independent
    # of whether Jedi supplies a CALLS target.
    assert all('targets' not in row for row in subscriptions + writes)


def test_relative_import_keeps_negative_container_source(tmp_path):
    result = analyze(tmp_path, {
        'src/pkg/__init__.py': '',
        'src/pkg/provider.py': 'handlers={}\n',
        'src/pkg/reader.py': 'from .provider import handlers\ndef run():handlers["go"]()\n',
    }, closed=False)
    by_id = {node['node_id']: node for node in result[0]}
    assert any(by_id[row['consumer_owner']]['qualname'] == 'run'
               for row in result[2].get('_unit_subscriptions', []))


def test_lambda_parameter_keeps_tool_located_argument_source(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def first():pass\n'
                     'execute=lambda callback:callback()\nexecute(first)\n'}, closed=False)
    nodes = {node['node_id']: node for node in result[0]}
    records = [row for row in result[2].get('_unit_supports', [])
               if row['kind'] == 'actual-parameter'
               and nodes[row['consumer_owner']]['node_type'] == 'lambda']
    assert any(row['detail']['parameter'] == 'callback'
               and row['producer_location']['expression'] == 'first' for row in records)


def test_argument_after_unknown_unpack_is_not_falsely_bound_exactly(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def take(a,b,c):pass\n'
                     'def run(xs,y):take(*xs,y)\n'}, closed=False)
    records = [row for row in result[2].get('_unit_supports', [])
               if row['kind'] == 'actual-parameter'
               and row['producer_location']['expression'] == 'y']
    assert {row['detail']['parameter'] for row in records} == {'a', 'b', 'c'}
    assert all(row['status'] == 'candidate' and row['detail']['source_uncertain']
               for row in records)


def test_variadic_parameter_keeps_all_explicit_argument_sources(tmp_path):
    result = analyze(tmp_path, {'demo.py': 'def first():pass\ndef second():pass\n'
                     'def take(*callbacks):pass\ndef run():take(first,second)\n'}, closed=False)
    records = [row for row in result[2].get('_unit_supports', [])
               if row['kind'] == 'actual-parameter'
               and row['detail']['parameter'] == 'callbacks']
    assert {row['producer_location']['expression'] for row in records} == {'first', 'second'}


def test_warm_jedi_work_does_not_grow_with_unrelated_consumers(tmp_path):
    import collections
    import jedi
    results = []
    for count in (0, 20, 100):
        config, repo = initialize(tmp_path / f'growth-{count}')
        (repo / 'src/weights.py').unlink()
        (repo / 'docs/guide.md').unlink()
        (repo / 'src/client.py').write_text('from provider import handlers\n'
                                          'def run():handlers["go"]()\n')
        (repo / 'src/noop.py').write_text('def noop():pass\n')
        for index in range(count):
            (repo / f'src/idle_{index}.py').write_text(
                f'from noop import noop\ndef idle_{index}():noop()\n')
        provider = repo / 'src/provider.py'
        provider.write_text('def first():pass\ndef second():pass\nhandlers={"go":first}\n')
        with forbid_provider():
            build(config, offline=True, lexical_only=True)
        provider.write_text('def first():pass\ndef second():pass\nhandlers={"go":second}\n')
        counts = collections.Counter()
        def watch(api, original):
            def observed(script, *args, **kwargs):
                counts[api, str(script.path), repr(args), repr(sorted(kwargs.items()))] += 1
                return original(script, *args, **kwargs)
            return observed
        with forbid_provider(), \
             patch.object(jedi.Script, 'infer', watch('infer', jedi.Script.infer)), \
             patch.object(jedi.Script, 'get_signatures', watch('signature', jedi.Script.get_signatures)), \
             patch.object(jedi.Script, 'goto', watch('goto', jedi.Script.goto)):
            result = build(config, offline=True, lexical_only=True)
        assert counts and max(counts.values()) == 1
        scope = result['incremental']['analysis_scope']
        assert scope['mode'] == 'incremental-owners'
        assert not any(':function:idle_' in owner for owner in scope['selected_owner_ids'])
        results.append((sum(counts.values()), scope['selected_owner_count']))
    assert results[0] == results[1] == results[2], results
