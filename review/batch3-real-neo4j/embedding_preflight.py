"""Read-only budgeting from persisted inputs; makes no API calls."""
import json, sqlite3, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from lct.extract import embedding_texts
from lct.embedding import bound
root=Path(__file__).resolve().parents[2]
p=Path('/tmp/lct-b3-locality-fixed-20261028/versions/20261028T122745-62019ae507/catalog.sqlite')
with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
    nodes=[json.loads(r[0]) for r in db.execute('select data from nodes order by node_id')]
    files=[dict(zip(('repository','path','text'),r)) for r in db.execute('select repository,path,text from files')]
texts=embedding_texts(nodes,files)
unique=list(dict.fromkeys(t['text'] for t in texts))
size=count=0; batches=[]
for t in unique+[None]:
    if count and (t is None or size+bound(t)>70000 or count>=64):
        batches.append({'items':count,'bound':size});size=count=0
    if t is not None:size+=bound(t);count+=1
cases=json.loads((root/'review/evaluation-expected.json').read_text())['cases']
checks=[]
for c in cases:
    expected=[n['node_id'] for n in nodes if n['repository']==c['repo'] and (not c.get('expected_name') or n['qualname']==c['expected_name']) and (not c.get('expected_path') or n['path']==c['expected_path']) and (c['level']=='all' or n['kind']==c['level'])] if c.get('expected_name') or c.get('expected_path') else []
    checks.append({'id':c['id'],'known_label_matches':len(expected),'node_ids':expected,'has_frozen_expected':bool(c.get('expected_name') or c.get('expected_path'))})
r={'api_requests':0,'input_chunks':len(texts),'unique_inputs':len(unique),'document_bound':sum(bound(t) for t in unique),'request_batches':len(batches),'max_input_bound':max(map(bound,unique)),'query_count':len(cases),'query_bound':sum(bound(c['query']) for c in cases),'price_from_existing_config':0.12,'proposed_max_cost_usd':1,'proposed_max_reserved_tokens':8000000,'proposed_max_attempts':120,'label_checks':checks,'limits':'Only verifies entry labels exist; not semantic relevance or retrieval quality. No budget approval inferred.'}
r['document_list_price_bound_usd']=r['document_bound']*.12/1000000
(root/'review/batch3-real-neo4j/embedding_preflight.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in r.items() if k!='label_checks'},ensure_ascii=False))
print([(c['id'],c['known_label_matches']) for c in checks])
