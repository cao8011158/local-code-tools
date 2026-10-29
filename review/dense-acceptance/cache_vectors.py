"""Populate existing embedding cache from frozen catalog, without source reanalysis."""
import os,sys,json,sqlite3,time
from pathlib import Path
root=Path('/tmp/lct-b3-isolated-v2-20261029');sys.path.insert(0,str(root))
from lct.common import config,atomic
from lct.embedding import Embeddings
from lct.extract import embedding_texts
from lct.storage import manifest,validate_folder
c=config(root/'config.json');folder,m=manifest(c);validate_folder(folder,m)
with sqlite3.connect((folder/'catalog.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True) as db:
 nodes=[json.loads(r[0]) for r in db.execute('select data from nodes order by node_id')]
 files=[dict(zip(('repository','path','text'),r)) for r in db.execute('select repository,path,text from files')]
texts=embedding_texts(nodes,files)
cache=Embeddings(c);started=time.monotonic()
try:
 cache.get_many([t['text'] for t in texts])
 cases=json.loads(Path('/workspace/scratch/413372d9a5a5/lct-staged-import/review/evaluation-expected.json').read_text())['cases']
 cache.get_many([x['query'] for x in cases],kind='query')
 result={'status':'PASS','version':m['version'],'chunks':len(texts),'new_vectors':cache.new_vectors,'requests':cache.requests,'seconds':time.monotonic()-started,'ledger':cache.ledger(),'authorized_ceiling_usd':3,'effective_existing_ceiling_usd':2}
except Exception as e:
 result={'status':'STOPPED','error_type':type(e).__name__,'error':str(e) if type(e).__name__=='ToolError' else 'details withheld','ledger':cache.ledger(),'seconds':time.monotonic()-started}
finally:
 cache.close();os.environ.pop('VOYAGE_API_KEY',None)
atomic(Path('/workspace/scratch/413372d9a5a5/lct-staged-import/review/dense-acceptance/cache-result.json'),result)
print(json.dumps(result),flush=True)
