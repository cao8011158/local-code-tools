"""Count exact importer preparation/writes without a database; not DB memory evidence."""
import collections, hashlib, json, sys, types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
storage=types.ModuleType('lct.storage')
def unused(*a,**kw): raise AssertionError('load_snapshot is outside this synthetic probe')
storage.manifest=storage.validate_folder=unused
sys.modules['lct.storage']=storage
from lct import neo4j_graph as m
class Counted(list):
    def __init__(self,rows): super().__init__(rows); self.visits=0;self.passes=0
    def __iter__(self):
        self.passes+=1
        for v in super().__iter__():self.visits+=1;yield v
class Result:
    def __init__(self,row=None):self.row=row
    def consume(self):return None
    def single(self,**kw):return self.row
class Spy:
    def __init__(self,fp,existing):
        self.fp=fp;self.existing=existing;self.queries=collections.Counter();self.ids=collections.defaultdict(list);self.tx_count=0
    def session(self,**kw):return self
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def begin_transaction(self,**kw):self.tx_count+=1;return self
    def run(self,q,**kw):
        if q.startswith('CREATE CONSTRAINT'):label='schema'
        elif 'ON CREATE SET' in q:
            self.queries['scope']+=1;return Result({'fingerprint':self.fp,'complete':self.existing})
        elif 'CREATE (n:' in q:label='node'
        elif 'CREATE (e:' in q:label='edge'
        elif 'CREATE (a)-' in q:label='relation'
        elif 'SET s.graph_json' in q:label='metadata'
        else:raise AssertionError(q)
        self.queries[label]+=1
        if label in ('node','edge','relation'):
            key='node_id' if label=='node' else 'edge_id'
            self.ids[label].extend(r[key] for r in kw['rows'])
        return Result()
def probe(n,e,existing):
    nodes=Counted({'node_id':f'n{i}','kind':list(m.NODE_LABELS)[i%5]} for i in range(n))
    edges=Counted({'edge_id':f'e{i}','kind':sorted(m.REL_TYPES)[i%7],'source':f'n{i%n}','target':f'n{(i+1)%n}'} for i in range(e))
    graph={'sites':[]};source={}
    fp=m.digest(m._snapshot_payload(nodes,edges,graph,source))
    snap=dict(version='v',nodes=nodes,edges=edges,graph=graph,source=source,fingerprint=fp)
    nodes.visits=nodes.passes=edges.visits=edges.passes=0
    orig=m.canonical;calls=collections.Counter();sizes=collections.Counter()
    def measured(value):
        k='snapshot' if isinstance(value,dict) and set(value)=={'nodes','edges','graph','source'} else 'graph' if value is graph else 'source' if value is source else 'row'
        s=orig(value);calls[k]+=1;sizes[k]+=len(s.encode());return s
    m.canonical=measured
    spy=Spy(fp,existing);obj=object.__new__(m.Neo4jGraph);obj.driver=spy;obj.database='neo4j'
    try:r=obj.import_snapshot('count-only', 'v', snap)
    finally:m.canonical=orig
    assert spy.tx_count==1
    for label,count in [('node',n),('edge',e),('relation',e)]:
        ids=spy.ids[label]
        assert len(ids)==len(set(ids))==(0 if existing else count)
    assert r['already_present']==existing
    return dict(n=n,e=e,already_present=existing,node_visits=nodes.visits,edge_visits=edges.visits,node_passes=nodes.passes,edge_passes=edges.passes,canonical_calls=dict(calls),canonical_bytes=dict(sizes),statements=dict(spy.queries),write_rows={k:len(v) for k,v in spy.ids.items()},duplicate_writes=0)
results=[probe(n,e,done) for n,e in [(100,500),(1000,5000)] for done in (False,True)]
report={'source_sha':'4557d4cd2c5a6b33933b3832f81dfb64207e4e4b','source_git_blob':'7b875e733228261a0e374d0e58973fc2685c108d','scope':'Exact import_snapshot method with counting lists and fake driver; no load_snapshot, Neo4j execution, or DB-memory claim','results':results}
(ROOT/'review/import-memory-diagnostic/counts.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
