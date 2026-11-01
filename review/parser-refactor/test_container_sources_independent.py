"""Actual public builds: per-read work and new/deleted writer invalidation."""
import json
import sqlite3

import pytest

from lct.storage import build, manifest
from tests.synthetic_support import initialize, forbid_provider


def read_site(config, version, expression):
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
        return next(json.loads(raw) for (raw,) in db.execute('select data from sites')
                    if json.loads(raw)['expression'] == expression)


@pytest.mark.parametrize('placement', ['module', 'local'])
def test_unrelated_function_dictionary_writers_do_not_grow_reads(tmp_path, placement):
    rows = []
    for noise in (0,20,100):
        c, repo = initialize(tmp_path / f'case-{noise}')
        (repo / 'src/weights.py').unlink()
        (repo / 'docs/guide.md').unlink()
        binding = ('handlers={"go":first}\ndef run(): handlers["go"]()\n'
                   if placement == 'module' else
                   'def run():\n handlers={"go":first}\n handlers["go"]()\n')
        source = 'def first():pass\n' + binding + ''.join(
            f'def noise_{i}():\n local={{}}\n local["x"]=first\n' for i in range(noise))
        (repo / 'src/example.py').write_text(source)
        with forbid_provider():
            result = build(c, offline=True, lexical_only=True)
        s = read_site(c, result['version'], "handlers['go']")
        assert len(s['targets']) == 1 and ':function:first#' in s['targets'][0]
        rows.append((result['graph'], s))
    first, first_site = rows[0]
    for graph, s in rows[1:]:
        assert s['complete'] == first_site['complete']
        assert s['unresolved_reasons'] == first_site['unresolved_reasons']
        assert graph['slot_scope_candidates_checked'] <= first['slot_scope_candidates_checked']
        assert graph['slot_events_checked'] <= first['slot_events_checked']


def test_new_changed_deleted_imported_writer_updates_negative_reader(tmp_path):
    c, repo = initialize(tmp_path / 'writers')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    c['retained_versions'] = 8
    (repo / 'src/base.py').write_text('def first():pass\ndef second():pass\nhandlers={}\n')
    (repo / 'src/reader.py').write_text('from base import handlers\ndef run(): handlers["go"]()\n')
    versions=[];original=None
    for state in (None,'first','second',None):
        writer = repo / 'src/writer.py'
        if state:
            writer.write_text('from base import handlers, first, second\n'+f'handlers["go"]={state}\n')
        elif writer.exists():
            writer.unlink()
        with forbid_provider():
            result = build(c, offline=True, lexical_only=True)
        s = read_site(c, result['version'], "handlers['go']")
        if state:
            assert any(f':function:{state}#' in target for target in s['targets'])
        else:
            assert not s['targets']
        if versions:
            assert result['incremental']['analysis_scope']['mode'] == 'incremental-owners'
        else:
            original=s
        versions.append(result['version'])
        assert read_site(c, versions[0], "handlers['go']") == original


def test_unrelated_module_calls_do_not_force_second_container_analysis(tmp_path):
    rows=[]
    for count in (0,20,100):
        c,repo=initialize(tmp_path / f'calls-{count}')
        (repo/'src/weights.py').unlink()
        (repo/'docs/guide.md').unlink()
        (repo/'src/example.py').write_text(
            'def first():pass\ndef noop():pass\nhandlers={"go":first}\n'
            'def run():handlers["go"]()\n'+'noop()\n'*count)
        with forbid_provider():
            result=build(c,offline=True,lexical_only=True)
        s=read_site(c,result['version'],"handlers['go']")
        assert len(s['targets'])==1 and ':function:first#' in s['targets'][0]
        rows.append(result['graph'])
    assert all(row['slot_events_checked']<=rows[0]['slot_events_checked'] for row in rows[1:])


def test_origin_preparation_reuses_actual_jedi_observations(tmp_path):
    import collections
    from unittest.mock import patch
    import jedi
    from tests.test_python_pipeline import analyze, site
    counts=collections.Counter()
    def wrapped(api,original):
        def watch(script,*args,**kwargs):
            key=(api,str(script.path),repr(args),repr(sorted(kwargs.items())))
            counts[key]+=1
            return original(script,*args,**kwargs)
        return watch
    sources={'base.py':'def first():pass\nhandlers={}\n',
             'writer.py':'from base import handlers, first\nhandlers["go"]=first\n',
             'reader.py':'from base import handlers\ndef run():handlers["go"]()\n'}
    with patch.object(jedi.Script,'infer',wrapped('infer',jedi.Script.infer)), \
         patch.object(jedi.Script,'goto',wrapped('goto',jedi.Script.goto)):
        result=analyze(tmp_path,sources,closed=False)
    assert site(result,"handlers['go']",'run')['names']=={'first'}
    assert counts and max(counts.values())==1,dict(counts)
    assert sum(counts.values())==result[2]['jedi_queries_executed']


def test_warm_update_reuses_unrelated_call_targets(tmp_path):
    rows=[]
    for count in (0,20,100):
        c,repo=initialize(tmp_path/f'warm-{count}')
        (repo/'src/weights.py').unlink()
        (repo/'docs/guide.md').unlink()
        (repo/'src/utility.py').write_text('def noop():pass\n')
        for i in range(count):
            (repo/f'src/noise_{i}.py').write_text(
                f'from utility import noop\ndef idle_{i}():noop()\n')
        path=repo/'src/active.py'
        def source(name):
            return ('def first():pass\ndef second():pass\nhandlers={"go":'+name+
                    '}\ndef run():handlers["go"]()\n')
        path.write_text(source('first'))
        with forbid_provider():
            build(c,offline=True,lexical_only=True)
        path.write_text(source('second'))
        with forbid_provider():
            result=build(c,offline=True,lexical_only=True)
        s=read_site(c,result['version'],"handlers['go']")
        assert len(s['targets'])==1 and ':function:second#' in s['targets'][0]
        assert result['incremental']['analysis_scope']['mode']=='incremental-owners'
        rows.append((result['graph'],result['incremental']['analysis_scope']))
    assert all(g['jedi_queries_executed']<=rows[0][0]['jedi_queries_executed'] for g,_ in rows[1:])
    assert all(g['jedi_query_entries']<=rows[0][0]['jedi_query_entries'] for g,_ in rows[1:])
    assert all(s['selected_owner_count']==rows[0][1]['selected_owner_count'] for _,s in rows[1:])


def test_definition_default_rebinding_does_not_mutate_earlier_alias(tmp_path):
    from tests.test_python_pipeline import analyze, site
    source=('def first():pass\ndef second():pass\ndef third():pass\n'
            'handlers={"go":first}\nold=handlers\n'
            'def sentinel(x=(handlers:={"go":second})):pass\n'
            'handlers["go"]=third\ndef run():old["go"]()\n')
    result=analyze(tmp_path,{'src/example.py':source},closed=False)
    s=site(result,"old['go']",'run')
    assert s['names']=={'first'}
    assert not s['resolution_decision']['excluded_jedi_targets']
