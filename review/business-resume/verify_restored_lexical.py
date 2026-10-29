"""Compare real lexical retrieval and source/graph identity after package relocation."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--toolkit',required=True);p.add_argument('--config',required=True);p.add_argument('--output',required=True);p.add_argument('--expected');p.add_argument('--require-no-live',action='store_true');a=p.parse_args()
sys.path.insert(0,str(Path(a.toolkit).resolve()))
from lct.common import config,canonical
from lct.query import Query
from lct.storage import manifest
from lct.embedding import Embeddings

def denied(*args,**kwargs):raise AssertionError('No embedding request permitted')
Embeddings.call=denied
c=config(a.config);folder,m=manifest(c);q=Query(c)
record={'version':m['version'],'source_fingerprint':m['source_fingerprint'],'program_hash':m['program_hash'],'repositories':{r['name']:r['head'] for r in m['repositories']},'graph_sha256':hashlib.sha256(canonical(m['graph']).encode()).hexdigest(),'artifacts':m['artifacts'],'dense_ready':m['dense_ready'],'searches':{},'sources':{}}
ids=[]
for level,text in [('module','environment'),('class','EnvironmentService'),('function','snapshot')]:
 r=q.search_code(text,level=level,mode='bm25',limit=5)
 assert r['results'],(level,text)
 hits=[x['node_id'] for x in r['results']];record['searches'][level]=hits;ids.append(hits[0])
d=q.search_docs('snapshot',limit=5);assert d['results'];record['searches']['docs']=[x['node_id'] for x in d['results']]
for row in q.get_nodes(ids,max_bytes=200000)['nodes']:
 assert row['source_origin']=='indexed_snapshot' and row['source'] and not row['source_truncated']
 if a.require_no_live:assert row['live_file_matches'] is False
 record['sources'][row['node_id']]=hashlib.sha256(row['source'].encode()).hexdigest()
relations=q.get_relations(ids,depth=1,max_nodes=100,max_edges=200)
record['relations_sha256']=hashlib.sha256(canonical(relations).encode()).hexdigest()
if a.expected:
 expected=json.loads(Path(a.expected).read_text());assert record==expected,'restored observable identities/results differ'
Path(a.output).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'PASS','version':m['version'],'dense_ready':m['dense_ready'],'search_kinds':list(record['searches']),'source_checks':len(record['sources']),'restored_comparison':bool(a.expected),'required_no_live_sources':a.require_no_live}))
