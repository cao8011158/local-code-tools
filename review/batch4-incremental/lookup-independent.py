"""Independent public-build/query acceptance for pending import lookup adjacency."""
import copy
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from lct.common import config
from lct.storage import build, manifest
from lct.query import Query

with tempfile.TemporaryDirectory(prefix='lct-lookup-review-') as tmp:
    root = Path(tmp) / 'repo'
    (root / 'src').mkdir(parents=True)
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'review@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Review'], check=True)
    sources={'a.py':'def existing(): pass\n', 'b.py':'from a import new_handler as h\n',
             'c.py':'from a import new_handler\n', 'other.py':'def unrelated(): pass\n'}
    for p,t in sources.items(): (root/'src'/p).write_text(t)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-m', 'fixture'], check=True, capture_output=True)
    c=copy.deepcopy(config(Path(__file__).resolve().parents[2] / "config.example.json")); c['repositories']=[dict(name='fixture',path=str(root),code_roots=['src'])]
    c['data']=str(Path(tmp)/'data'); c['embedding']['historical_cache']='none'
    first=build(c, offline=True, lexical_only=True)
    folder,_=manifest(c,first['version']); db=sqlite3.connect(folder/'catalog.sqlite')
    nodes=[json.loads(r[0]) for r in db.execute('select data from nodes')]
    a=next(n['node_id'] for n in nodes if n['kind']=='module' and n['qualname']=='a')
    q=Query(c)
    related=q.get_relations([a], direction='in', depth=2, relation_types=['LOOKUP_IN','IMPORTS'],version=first['version'])
    assert len([e for e in related['edges'] if e['kind']=='IMPORTS'])==2, related
    assert len([e for e in related['edges'] if e['kind']=='LOOKUP_IN'])==1, related
    original=json.dumps(related["edges"],sort_keys=True)
    # Measure actual SQL shape against same schema with unrelated edges added in a separate database.
    measure=sqlite3.connect(':memory:'); db.backup(measure)
    ids=[a, next(e['target'] for e in related['edges'] if e['kind']=='IMPORTS')]
    sql='select data from edges where target=? and kind in (?,?) order by edge_id limit ?'
    def cost():
        ticks=[0]; measure.set_progress_handler(lambda: ticks.__setitem__(0,ticks[0]+1) or 0,1)
        rows=[list(measure.execute(sql,(nid,'LOOKUP_IN','IMPORTS',201))) for nid in ids]
        measure.set_progress_handler(None,0)
        return {'vm_steps':ticks[0],'rows':sum(map(len,rows))}
    cold=cost(); warm=cost()
    measure.executemany('insert into edges values(?,?,?,?,?,?)', [(f'noise-{i}',f'x-{i}',f'y-{i}','IMPORTS','resolved','{}') for i in range(10000)])
    expanded=cost()
    assert expanded['rows']==cold['rows']==3
    assert expanded['vm_steps'] <= warm['vm_steps']+20, (cold,expanded)
    plans=[r[3] for r in measure.execute('explain query plan '+sql,(a,'LOOKUP_IN','IMPORTS',201))]
    assert any('edge_target' in p for p in plans),plans
    (root/'src/a.py').write_text('def existing(): pass\ndef new_handler(): pass\n')
    second=build(c,offline=True,lexical_only=True)
    assert json.dumps(q.get_relations([a],direction='in',depth=2,relation_types=['LOOKUP_IN','IMPORTS'],version=first['version'])["edges"],sort_keys=True)==original
    newfolder,_=manifest(c,second['version'])
    with sqlite3.connect(newfolder/'catalog.sqlite') as newdb:
        assert newdb.execute("select count(*) from edges where kind='LOOKUP_IN'").fetchone()[0]==0
        imports=[json.loads(r[0]) for r in newdb.execute("select data from edges where kind='IMPORTS'")]
        assert len(imports)==2 and all(e['status']=='resolved' for e in imports)
    print(json.dumps({'public_build_query':'passed','old_snapshot':'unchanged','transition':'unresolved to resolved',
                      'sqlite_plan':plans,'before_cold':cold,'before_warm':warm,'after_10000_unrelated_edges':expanded,
                      'paid_api_calls':0,'analysis':'full build; not an incremental analyzer test'},ensure_ascii=False,indent=2))
