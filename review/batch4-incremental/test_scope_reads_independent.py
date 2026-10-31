"""Root's independent semantic-origin ledger and actual consumer checks."""
import json
import sqlite3

import pytest

from lct.common import ToolError
from lct.storage import FileDependencies, build, current, manifest
from tests.synthetic_support import initialize
from tests.test_python_pipeline import analyze


def modules(result):
    return {n['node_id']:n['path'] for n in result[0] if n['kind']=='module'}


def read_paths(result):
    mapping=modules(result)
    return {(mapping[c],mapping[p],kind) for c,p,kind in result[2]['_analysis_reads']}


def test_matched_callback_origin_excludes_rejected_candidates(tmp_path):
    sources={'src/provider.py':'def execute(callback): callback()\n',
             'src/caller.py':'from provider import execute\ndef first(): pass\ndef launch(): execute(first)\n'}
    sources.update({f'src/noise_{i}.py':f'def unrelated_{i}(other): other()\n' for i in range(20)})
    result=analyze(tmp_path,sources)
    reads=read_paths(result)
    assert ('src/provider.py','src/caller.py','parameter-origin') in reads
    assert not any(c=='src/provider.py' and p.startswith('src/noise_') for c,p,_ in reads),reads
    assert result[2]['_analysis_dependency_truncated'] is False


def test_return_body_and_absent_member_keep_known_producer(tmp_path):
    result=analyze(tmp_path,{'src/provider.py':'class Box: pass\ndef factory(): return Box()\n',
        'src/consumer.py':'from provider import factory\ndef use(): factory().missing()\n'})
    reads=read_paths(result)
    assert ('src/consumer.py','src/provider.py','return-body') in reads
    assert ('src/consumer.py','src/provider.py','member-lookup') in reads
    missing=[s for s in result[2]['sites'] if s['expression']=='factory().missing']
    assert len(missing)==1 and missing[0]['unknown_origin'] is True


def make(tmp_path,noise=0):
    config,repo=initialize(tmp_path/'fixture')
    (repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
    (repo/'src/provider.py').write_text('def execute(callback): callback()\n')
    (repo/'src/caller.py').write_text('from provider import execute\ndef first(): pass\ndef second(): pass\ndef launch(): execute(first)\n')
    for i in range(noise):
        (repo/f'src/noise_{i}.py').write_text(f'def idle_{i}(): pass\n')
    return config,repo


def records(config,version):
    folder,_=manifest(config,version)
    out={}
    for file,tables in [('catalog.sqlite',('nodes','edges')),
                       ('graph-sites.sqlite',('sites','query_observations','import_dependencies',
                           'import_requests','analysis_reads','analysis_watches','value_nodes','value_edges','value_reads'))]:
        with sqlite3.connect(folder/file) as db:
            for table in tables:
                if table in {'analysis_reads','analysis_watches','value_edges','value_reads'}:
                    out[table]=sorted(tuple(r) for r in db.execute(f'select * from {table}'))
                else:out[table]=sorted(json.dumps(json.loads(s),sort_keys=True) for (s,) in db.execute(f'select data from {table}'))
    return out


@pytest.mark.parametrize('noise',[0,20])
def test_public_update_consumes_observed_readers_and_preserves_full_results(tmp_path,monkeypatch,noise):
    import lct.extract as extraction
    config,repo=make(tmp_path,noise)
    first=build(config,offline=True,lexical_only=True)
    old=records(config,first['version'])
    folder,meta=manifest(config,first['version'])
    with FileDependencies(folder,meta) as dependencies:
        rows=list(dependencies.db.execute("select consumer_path,producer_path,kind from analysis_reads where kind='parameter-origin'"))
        assert ('src/provider.py','src/caller.py','parameter-origin') in rows
        assert ('synthetic-review','src/provider.py') in dependencies.analysis_readers('synthetic-review','src/caller.py')
    calls=[];reads=[];extract=extraction.python_nodes;readers=FileDependencies.analysis_readers
    def track(file):calls.append(file['path']);return extract(file)
    def track_read(self,repository,path):reads.append((repository,path));return readers(self,repository,path)
    monkeypatch.setattr(extraction,'python_nodes',track)
    monkeypatch.setattr(FileDependencies,'analysis_readers',track_read)
    caller=repo/'src/caller.py';caller.write_text(caller.read_text().replace('execute(first)','execute(second)'))
    with pytest.raises(ToolError,match='Injected'):
        build(config,offline=True,lexical_only=True,fail_at='before_publish')
    assert current(config)==first['version'] and records(config,first['version'])==old
    calls.clear();reads.clear()
    updated=build(config,offline=True,lexical_only=True)
    assert sorted(calls)==['src/caller.py','src/provider.py']
    assert ('synthetic-review','src/caller.py') in reads
    assert not any(path.startswith('src/noise_') for _,path in reads)
    oracle=dict(config,data=str(tmp_path/'oracle'));full=build(oracle,offline=True,lexical_only=True)
    assert records(config,updated['version'])==records(oracle,full['version'])
    assert records(config,first['version'])==old


def test_dependency_record_exhaustion_cannot_change_analysis(tmp_path,monkeypatch):
    import lct.python_analysis as analysis
    sources={'src/provider.py':'def execute(callback): callback()\n',
        'src/caller.py':'from provider import execute\ndef first(): pass\ndef launch(): execute(first)\n'}
    before=analyze(tmp_path,sources)
    monkeypatch.setattr(analysis,'ANALYSIS_DEPENDENCY_LIMIT',0)
    after=analyze(tmp_path,sources)
    assert before[0]==after[0] and before[1]==after[1]
    assert before[2]['sites']==after[2]['sites']
    assert after[2]['_analysis_dependency_truncated'] is True
    assert not after[2]['_analysis_reads'] and not after[2]['_analysis_watches']


def test_actual_parameter_reader_index_does_not_scan_unrelated_origins(tmp_path):
    measured=[]
    for noise in (0,15):
        config,repo=make(tmp_path/str(noise))
        for i in range(noise):
            (repo/f'src/other_provider_{i}.py').write_text('def target(): pass\n')
            (repo/f'src/other_caller_{i}.py').write_text(f'from other_provider_{i} import target\ndef expose(): return target\n')
        result=build(config,offline=True,lexical_only=True)
        folder,meta=manifest(config,result['version'])
        assert not result['graph']['analysis_limited']
        with FileDependencies(folder,meta) as deps:
            size=deps.db.execute('select count(*) from analysis_reads').fetchone()[0]
            matching=deps.db.execute("select count(*) from analysis_reads where producer_repository=? and producer_path=?",('synthetic-review','src/caller.py')).fetchone()[0]
            total=[0];sql=[]
            def tick():total[0]+=1;return 0
            deps.db.set_progress_handler(tick,1);deps.db.set_trace_callback(sql.append)
            found=deps.analysis_readers('synthetic-review','src/caller.py')
            deps.db.set_progress_handler(None,0);deps.db.set_trace_callback(None)
            assert found=={('synthetic-review','src/provider.py')}
            plans=[r[3] for query in sql for r in deps.db.execute('explain query plan '+query)]
            assert plans and all('SEARCH' in p and 'analysis_read_producer' in p and 'SCAN' not in p for p in plans)
            measured.append(dict(noise_pairs=noise,total_records=size,matching_records=matching,vm_steps=total[0],
                                 result_rows=len(found),statements=len(sql),plans=plans))
    assert measured[1]['total_records']>measured[0]['total_records']
    assert measured[0]['matching_records']==measured[1]['matching_records']
    assert measured[0]['vm_steps']==measured[1]['vm_steps']
    assert measured[0]['statements']==measured[1]['statements']==1
    print('PARAMETER_ORIGIN_INDEX='+json.dumps(measured,sort_keys=True))
