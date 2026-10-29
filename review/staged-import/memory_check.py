"""Real Neo4j staged import with a synthetic 61,164,381-byte graph value.

Measures sampled retained transaction heap at write boundaries, not total JVM peak.
Run only under an owned-service launcher. No API or business source analysis.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from neo4j import GraphDatabase
from lct.common import canonical, digest
from lct.neo4j_graph import Neo4jGraph

uri=os.environ['LCT_TEST_NEO4J_URI']
auth=(os.environ['LCT_TEST_NEO4J_USER'],os.environ['LCT_TEST_NEO4J_PASSWORD'])
database=os.environ['LCT_TEST_NEO4J_DATABASE']
namespace='staged-memory-'+uuid4().hex
nodes=[dict(node_id=f'n{i}',kind='function') for i in range(100)]
edges=[dict(edge_id=f'e{i}',kind='CALLS',source=f'n{i%100}',target=f'n{(i+1)%100}') for i in range(500)]
graph={'evidence':'x'*(61_164_381-len(canonical({'evidence':''}).encode()))}
source={'synthetic':True}
snapshot=dict(version='v',nodes=nodes,edges=edges,graph=graph,source=source)
snapshot['fingerprint']=digest(canonical({k:snapshot[k] for k in ('nodes','edges','graph','source')}))
observations=[]; writes=[]; commits=[]
started=time.monotonic()
with GraphDatabase.driver(uri,auth=auth) as observer, Neo4jGraph(uri,*auth,database) as db:
    original=db.driver
    def observe():
        with observer.session(database='system') as session:
            rows=session.run('SHOW TRANSACTIONS YIELD database,estimatedUsedHeapMemory,currentQuery '
                             'RETURN database,estimatedUsedHeapMemory,currentQuery')
            values=[r['estimatedUsedHeapMemory'] for r in rows if r['database']==database and isinstance(r['estimatedUsedHeapMemory'],int)]
            observations.append(max(values,default=0))
    class Result:
        def __init__(self,result,sample):self.result=result;self.sample=sample
        def consume(self):
            value=self.result.consume()
            if self.sample:observe()
            return value
        def single(self,*args,**kw):return self.result.single(*args,**kw)
        def __iter__(self):return iter(self.result)
    class Tx:
        def __init__(self,tx):self.tx=tx
        def __enter__(self):self.tx.__enter__();return self
        def __exit__(self,*args):
            result=self.tx.__exit__(*args)
            if args[0] is None:commits.append(1)
            return result
        def run(self,q,**params):
            rows=params.get('rows')
            sample=rows is not None
            if sample:
                writes.append({'rows':len(rows),'record_bytes':sum(len(canonical(r).encode()) for r in rows),'chunk': 'LCTChunk' in q})
            return Result(self.tx.run(q,**params),sample)
    class Session:
        def __init__(self,s):self.s=s
        def __enter__(self):self.s.__enter__();return self
        def __exit__(self,*args):return self.s.__exit__(*args)
        def run(self,*args,**kwargs):return self.s.run(*args,**kwargs)
        def begin_transaction(self,**kwargs):return Tx(self.s.begin_transaction(**kwargs))
    class Driver:
        def session(self,**kwargs):return Session(original.session(**kwargs))
    db.driver=Driver()
    try:result=db.import_snapshot(namespace,'v',snapshot)
    finally:db.driver=original
    restored=db.snapshot_info(namespace,'v')
    assert restored['graph']==graph and restored['source']==source
    assert max(w['record_bytes'] for w in writes)<=1024*1024
    assert len(commits)>1
    with observer.session(database=database) as session:
        marker=session.run('MATCH (s:LCTSnapshot {namespace:$ns,version:"v"}) '
                           'RETURN s.complete AS complete,s.graph_json AS legacy',ns=namespace).single()
        assert marker['complete'] is True and marker['legacy'] is None
    record={'synthetic':True,'graph_bytes':len(canonical(graph).encode()),'nodes':len(nodes),'edges':len(edges),
            'committed_transactions':len(commits),'write_batches':len(writes),'chunk_batches':sum(w['chunk'] for w in writes),
            'max_batch_record_bytes':max(w['record_bytes'] for w in writes),
            'max_sampled_retained_transaction_heap':max(observations),'sample_count':len(observations),
            'exact_graph_source_roundtrip':True,'seconds':time.monotonic()-started,
            'import_source_sha256':hashlib.sha256((ROOT/'lct/neo4j_graph.py').read_bytes()).hexdigest(),
            'limits':'Repeated-character synthetic evidence. Samples after writes do not measure in-query/commit/JVM/Python peaks. No real business graph acceptance.'}
    path=ROOT/'review/staged-import/memory-result.json';path.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))
