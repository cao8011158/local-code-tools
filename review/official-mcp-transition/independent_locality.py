"""Independent scoped traversal cost comparison, with no paid API or user-data writes."""
import json
import os
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from lct.common import canonical,digest
from lct.neo4j_graph import Neo4jGraph
from lct.official_mcp import read_cypher_requests

def walk(p):
    yield p
    for c in p.get('children',[]): yield from walk(c)

def snapshot(extra):
    ns=[dict(node_id=x,kind='function',repository='fixture') for x in ['a','b']+[f'x{i}' for i in range(extra)]]
    es=[dict(edge_id=f'e{i}',kind='CALLS',source=s,target=t,status='unresolved' if t is None else 'candidate',complete=False,unknown_origin=True,basis='independent') for i,(s,t) in enumerate([('a','b'),('a',None),('a',None),('a','external:lib'),('external:lib','a'),('a','a')])]
    es += [dict(edge_id=f'x{i}',kind='CALLS',source=f'x{i}',target=f'x{i+1}',status='resolved',complete=True) for i in range(max(0,extra-1))]
    p=dict(nodes=ns,edges=es,graph={'sites':[]},source={'repositories':[]})
    return dict(**p,version='independent-v2',fingerprint=digest(canonical(p)))

if __name__=='__main__':
    report=[]
    args=[os.environ['LCT_TEST_NEO4J_'+k] for k in ('URI','USER','PASSWORD','DATABASE')]
    with Neo4jGraph(*args) as g:
        for extra in (0,1000):
            s=snapshot(extra); scope='independent-native-'+uuid.uuid4().hex
            g.import_snapshot(scope,s['version'],s)
            expected=sorted((e for e in s['edges'] if e['source']=='a' or e['target']=='a'),key=lambda e:e['edge_id'])
            req=read_cypher_requests(scope,s['version'],['a'],s['fingerprint'])[-1]['arguments']
            with g.driver.session(database=g.database) as db:
                result=db.run('PROFILE '+req['query'],**req['params']); rows=[dict(r) for r in result]; profile=result.consume().profile
                assert [json.loads(r['raw']) for r in rows]==expected
                unknown_ids=[r['target_boundary_id'] for r in rows if json.loads(r['raw']).get('target') is None]
                assert len(unknown_ids)==2 and len(set(unknown_ids))==2
                operators=list(walk(profile))
                assert not any(x['operatorType'].split('@')[0] in ('AllNodesScan','NodeByLabelScan') for x in operators),operators
                report.append(dict(unrelated_nodes=extra,returned=len(rows),db_hits=sum(x.get('dbHits',0) for x in operators),operators=[dict(operator=x['operatorType'],rows=x.get('rows'),db_hits=x.get('dbHits')) for x in operators]))
        assert report[1]['db_hits']<=report[0]['db_hits']*1.25+20,report
    (Path(__file__).with_name('independent-locality.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
