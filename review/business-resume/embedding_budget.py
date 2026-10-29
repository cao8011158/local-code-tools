"""Estimate current persisted input batches without extraction or provider requests."""
import json,sqlite3,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from lct.extract import embedding_texts
from lct.embedding import bound
c=json.loads(Path('/tmp/lct-b3-isolated-v2-20261029/config.json').read_text());data=Path(c['data']);v=json.loads((data/'current.json').read_text())['version'];p=data/'versions'/v/'catalog.sqlite'
with sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True) as db:
 nodes=[json.loads(x[0]) for x in db.execute('select data from nodes order by node_id')]
 files=[dict(zip(('repository','path','text'),x)) for x in db.execute('select repository,path,text from files')]
texts=embedding_texts(nodes,files);unique=list(dict.fromkeys(t['text'] for t in texts));batches=0;size=count=0
for text in unique+[None]:
 if count and (text is None or size+bound(text)>c['embedding']['batch_bytes'] or count>=c['embedding']['batch_items']):batches+=1;size=count=0
 if text is not None:size+=bound(text);count+=1
cases=json.loads((root/'review/evaluation-expected.json').read_text())['cases'];checks=[]
for case in cases:
 hits=[n['node_id'] for n in nodes if n['repository']==case['repo'] and (not case.get('expected_name') or n['qualname']==case['expected_name']) and (not case.get('expected_path') or n['path']==case['expected_path']) and (case['level']=='all' or n['kind']==case['level'])] if case.get('expected_name') or case.get('expected_path') else []
 checks.append({'id':case['id'],'label_matches':len(hits),'has_label':bool(case.get('expected_name') or case.get('expected_path'))})
r={'version':v,'paid_requests':0,'chunks':len(texts),'unique_inputs':len(unique),'document_bound':sum(bound(t) for t in unique),'batches_without_retries':batches,'max_input_bound':max(map(bound,unique)),'query_count':len(cases),'query_bound':sum(bound(x['query']) for x in cases),'configured_price_per_million_usd':c['embedding']['price_per_million_usd'],'label_presence':checks,'limitation':'Configured historical price only, not current billing quote; conservative byte bound, not provider measured tokens. No relevance evaluation yet.'}
r['configured_price_estimate_usd']=r['document_bound']*r['configured_price_per_million_usd']/1000000
(root/'review/business-resume/embedding-budget.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
