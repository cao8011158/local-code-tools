"""Root-authored closed common grammar, actual local updates and candidate locality."""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from lct.common import ToolError, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.storage import build,current,manifest
from tests.synthetic_support import initialize

FIXTURE=Path(__file__).with_name('fixtures')/'actual-source-subset'


def setup(tmp_path,noise=0,calls=False):
    config,repo=initialize(tmp_path/'fixture')
    (repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
    target=repo/'src/trpg_state_machine';target.mkdir()
    provenance=json.loads((FIXTURE/'provenance.json').read_text())
    for source in (FIXTURE/'src/trpg_state_machine').glob('*.py'):
        raw=source.read_bytes();expected=provenance['files']['src/trpg_state_machine/'+source.name]
        assert hashlib.sha256(raw).hexdigest()==expected['sha256']
        shutil.copyfile(source,target/source.name)
    for i in range(noise):
        (repo/f'src/noise_{i}.py').write_text(f'def idle_{i}(): pass\ndef run_{i}(): idle_{i}()\n' if calls else f'def idle_{i}(): pass\n')
    return config,repo,target


def records(config,version):
    folder,_=manifest(config,version);out={}
    for name,tables in [('catalog.sqlite',('nodes','edges')),
        ('graph-sites.sqlite',('sites','query_observations','import_dependencies','import_requests',
                              'analysis_reads','analysis_watches','value_nodes','value_edges','value_reads'))]:
        with sqlite3.connect(folder/name) as db:
            for table in tables:
                if table in {'analysis_reads','analysis_watches','value_edges','value_reads'}:
                    out[table]=sorted(tuple(row) for row in db.execute(f'select * from {table}'))
                else:out[table]=sorted(json.dumps(json.loads(raw),sort_keys=True) for (raw,) in db.execute(f'select data from {table}'))
    return out


@pytest.mark.parametrize('noise',[0,20])
def test_real_three_files_one_parse_oracle_old_view_and_failure(tmp_path,monkeypatch,noise):
    import lct.extract as extraction
    config,repo,target=setup(tmp_path,noise)
    first=build(config,offline=True,lexical_only=True)
    assert first['simple_python_certificate']=='simple-python-v6'
    old=records(config,first['version'])
    actual=extraction.python_nodes;parsed=[]
    def count(file):parsed.append(file['path']);return actual(file)
    monkeypatch.setattr(extraction,'python_nodes',count)
    path=target/'availability.py';raw=path.read_bytes();assert raw.count(b'context=context')==1
    path.write_bytes(raw.replace(b'context=context',b'context=None'))
    with pytest.raises(ToolError,match='Injected'):
        build(config,offline=True,lexical_only=True,fail_at='before_publish')
    assert current(config)==first['version'] and records(config,first['version'])==old
    parsed.clear();updated=build(config,offline=True,lexical_only=True)
    assert sorted(parsed)==sorted(['src/trpg_state_machine/availability.py']+[str(p.relative_to(repo)) for p in (repo/'src').rglob('*.py')])
    assert updated['incremental']['analysis_scope']['mode']=='full-graph'
    assert updated['incremental']['analysis_scope']['reason']=='changed-opaque-call-effect-unavailable'
    assert records(config,first['version'])==old
    fresh_config=dict(config,data=str(tmp_path/'oracle'));fresh=build(fresh_config,offline=True,lexical_only=True)
    assert records(config,updated['version'])==records(fresh_config,fresh['version'])
    parsed.clear();same=build(config,offline=True,lexical_only=True)
    assert parsed==[] and records(config,same['version'])==records(config,updated['version'])


def test_keyword_only_callback_cross_file_and_returned_field_remain_connected(tmp_path):
    config,repo,target=setup(tmp_path,20)
    (repo/'src/provider.py').write_text('def execute(callback, *, enabled: bool=True) -> None:\n    callback()\n')
    (repo/'src/caller.py').write_text('from provider import execute\ndef first(): pass\ndef second(): pass\ndef run(): execute(first,enabled=True)\n')
    first=build(config,offline=True,lexical_only=True)
    assert first['simple_python_certificate']=='simple-python-v6'
    path=repo/'src/caller.py';path.write_text(path.read_text().replace('execute(first,enabled=True)','execute(second,enabled=False)'))
    updated=build(config,offline=True,lexical_only=True)
    assert updated['incremental']['analysis_scope']['python_files_parsed']==1
    fresh_config=dict(config,data=str(tmp_path/'oracle'));fresh=build(fresh_config,offline=True,lexical_only=True)
    assert records(config,updated['version'])==records(fresh_config,fresh['version'])


@pytest.mark.parametrize('addition',[
    'def dataclass(value): return value\n',
    'def property(value): return value\n',
    'class Exception: pass\n',
])
def test_helpers_shadowed_in_common_module_cannot_receive_certificate(tmp_path,addition):
    config,repo,target=setup(tmp_path)
    path=target/'errors.py';path.write_text(path.read_text()+'\n'+addition)
    result=build(config,offline=True,lexical_only=True)
    assert result['simple_python_certificate'] is None


@pytest.mark.parametrize('shadow',['dataclasses','re'])
def test_new_stdlib_shadow_falls_back(tmp_path,shadow):
    config,repo,target=setup(tmp_path)
    first=build(config,offline=True,lexical_only=True)
    assert first['simple_python_certificate']=='simple-python-v6'
    (repo/f'src/{shadow}.py').write_text('def helper(): pass\n')
    result=build(config,offline=True,lexical_only=True)
    assert result['simple_python_certificate'] is None
    assert result['incremental']['analysis_scope']['mode']=='full-graph'


@pytest.mark.parametrize('noise',[0,200])
def test_candidate_and_constructor_reads_use_component_index(tmp_path,noise):
    from lct.simple_python import component_policy
    from lct.python_analysis import Analyzer
    config,repo,target=setup(tmp_path,noise,calls=True)
    files,repos,_=inventory(config);nodes,asts=extract(files);graph=Graph(nodes,asts,repos)
    policy=component_policy(files,asts,graph);assert policy is not None
    analyzer=Analyzer(graph.nodes,asts,repos,graph.imported,candidate_components=policy)
    try:
        function=next(n['node_id'] for n in nodes if n.get('qualname')=='AvailabilityRuntime.query_action_availability')
        expected=[s for s in analyzer.sites if analyzer.nodes[s['execution_owner']]['path'].endswith('/availability.py')]
        class IndexedOnly(list):
            reads=0
            def __iter__(self):raise AssertionError('known component scanned entire site list')
            def __getitem__(self,key):self.reads+=1;return super().__getitem__(key)
        guarded=IndexedOnly(analyzer.sites);analyzer.sites=guarded
        assert list(analyzer.candidate_sites(function))==expected
        assert list(analyzer.sites_for(function))==expected
        analyzer._query_inflight=1
        assert list(analyzer.candidate_sites(function))==expected
        assert guarded.reads==3*len(expected)
        analyzer._query_inflight=0
        guarded.append(dict(expected[0],execution_owner='unknown-new-owner'))
        assert analyzer.candidate_sites(function) is guarded
        assert analyzer.sites_for(function) is guarded
    finally:analyzer.close()


def test_connected_component_shares_membership_object(tmp_path):
    from lct.simple_python import component_policy
    config,repo=initialize(tmp_path/'connected')
    (repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
    (repo/'src/a.py').write_text('def first(): pass\n')
    (repo/'src/b.py').write_text('from a import first\ndef second(): first()\n')
    (repo/'src/c.py').write_text('from b import second\ndef third(): second()\n')
    files,repos,_=inventory(config);nodes,asts=extract(files);graph=Graph(nodes,asts,repos)
    policy=component_policy(files,asts,graph)
    modules=[n['node_id'] for n in nodes if n['kind']=='module']
    assert len(modules)==3 and policy is not None
    assert policy[modules[0]] is policy[modules[1]] is policy[modules[2]]
    assert policy[modules[0]]==frozenset(modules)
