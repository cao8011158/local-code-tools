"""Independent public-build counters and corrupted reuse evidence fallback."""
import sqlite3
import pytest
from lct import storage, dense_update
from tests.synthetic_support import initialize, seed_cache
from tests.test_incremental_query_reuse import commit, records, full_again


def test_docs_update_reuses_dense_without_constructing_index(tmp_path, monkeypatch):
    c,repo=initialize(tmp_path/'sample')
    seed_cache(c)
    old=storage.build(c,offline=True)
    count=len(old['partitions'])
    assert count>0
    old_folder,_=storage.manifest(c,old['version'])
    old_bytes={p.name:p.read_bytes() for p in old_folder.glob('partition-*')}
    (repo/'docs/guide.md').write_text('# Updated guide\nDocumentation only.\n')
    commit(repo,'docs')
    def forbidden(*a,**kw): raise AssertionError('unchanged dense partition rebuilt')
    monkeypatch.setattr(dense_update,'Index',forbidden)
    updated=storage.build(c,offline=True)
    assert updated['incremental']['dense_partitions_reused']==count
    assert updated['incremental']['dense_partitions_rebuilt']==0
    assert updated['embedding_run']['requests']==0
    assert updated['graph']['jedi_queries_reused']>0
    assert old_bytes=={p.name:p.read_bytes() for p in old_folder.glob('partition-*')}
    print({'dense_reused':count,'dense_rebuilt':0,'jedi_reused':updated['graph']['jedi_queries_reused'],'provider_requests':0})


def test_corrupt_query_artifact_falls_back_without_reusing(tmp_path, monkeypatch):
    c,repo=initialize(tmp_path/'sample')
    old=storage.build(c,lexical_only=True)
    folder,_=storage.manifest(c,old['version'])
    with sqlite3.connect(folder/'graph-sites.sqlite') as db:
        db.execute("update query_observations set checksum='wrong'")
        db.commit()
    (repo/'docs/guide.md').write_text('# Changed\n')
    commit(repo,'docs')
    updated=storage.build(c,lexical_only=True)
    assert updated['graph']['jedi_queries_reused']==0
    control=full_again(c,monkeypatch)
    assert records(c,updated['version'])[:3]==records(c,control['version'])[:3]
    print({'corrupt_cache':'full inference fallback','reused':0})

def test_external_python_dependency_change_does_not_reuse_stale_inference(tmp_path, monkeypatch):
    import sys
    c,repo=initialize(tmp_path/'sample')
    lib=tmp_path/'python-external';lib.mkdir()
    module=lib/'external_choice.py'
    module.write_text('def choose(left, right):\n    return left\n')
    monkeypatch.setattr(sys,'path',[*sys.path,str(lib)])
    source=repo/'src/external_user.py'
    source.write_text('from external_choice import choose\ndef first(): pass\ndef second(): pass\nselected = choose(first, second)\nselected()\n')
    commit(repo,'uses external library')
    storage.build(c,lexical_only=True)
    module.write_text('def choose(left, right):\n    return right\n')
    (repo/'docs/guide.md').write_text('# Change\n')
    commit(repo,'docs')
    updated=storage.build(c,lexical_only=True)
    control=full_again(c,monkeypatch)
    for label, version in [('reused',updated['version']),('full',control['version'])]:
        rows=records(c,version)
        print(label,[(e.get('expression'),e.get('target'),e.get('status'),e.get('complete')) for _,data in rows[1] if (e:=__import__('json').loads(data)).get('kind')=='CALLS' and 'external_user' in e.get('source','')])
    assert records(c,updated['version'])[:3]==records(c,control['version'])[:3]

def test_prepare_only_second_build_accepts_existing_dense_partitions(tmp_path):
    c,repo=initialize(tmp_path/'sample')
    seed_cache(c)
    original=storage.build(c,offline=True)
    candidate=storage.build(c,offline=True,prepare_only=True)
    assert storage.current(c)==original['version']
    assert candidate['incremental']['dense_partitions_reused']==len(original['partitions'])
