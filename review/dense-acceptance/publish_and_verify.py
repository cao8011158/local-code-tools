"""Complete offline dense attachment and bounded actual retrieval checks after API cache finishes."""
import json,sys,time,subprocess,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from lct.common import config,atomic,program_hash
from lct.embedding import Embeddings
from lct.storage import attach_dense
out=root/'review/dense-acceptance';cache_result=out/'cache-result.json'
deadline=time.monotonic()+900
while not cache_result.exists():
 if time.monotonic()>deadline:raise RuntimeError('Cache completion wait deadline')
 time.sleep(2)
r=json.loads(cache_result.read_text());assert r['status']=='PASS',r
Embeddings.call=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No provider permitted in offline publication'))
c=config('/tmp/lct-b3-isolated-v2-20261029/config.json')
m=attach_dense(c,'20261029T111748-7a235bf36f',offline=True,expected_program_hash='59c3b55f4f41d7925172042d31236b8064e9a655895ed06db942ff3d0655b4fc')
r={'status':'PUBLISHED','version':m['version'],'program_hash':m['program_hash'],'source_fingerprint':m['source_fingerprint'],'nodes':m['node_count'],'edges':sum(m['edges'].values()),'partitions':m['partitions'],'vector_chunks':m['vector_chunks'],'embedding_run':m['embedding_run'],'seconds':m['seconds'],'catalog_sha256':m['artifacts']['catalog.sqlite']}
atomic(out/'publication.json',r);print(json.dumps(r),flush=True)
args=[sys.executable,str(out/'verify.py'),'--toolkit',str(root),'--config',c['_path'],'--expected',str(root/'review/evaluation-expected.json'),'--output',str(out/'original-observations.json'),'--baseline-version','20261029T111748-7a235bf36f','--baseline-nodes','5957','--baseline-edges','42492','--baseline-graph-sha256','1b220e9c80aca289ba2a7c86ffcf09d0a2cae9874310c96cd4bb2ebd2951e13b','--baseline-source-fingerprint','12fe107f9c97d29261ea06cfd60c5c0e72e0a6a93aac9abb3af63c156de052fd']
p=subprocess.run(args,capture_output=True,text=True,timeout=120)
atomic(out/'retrieval-result.json',dict(exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr))
print(p.stdout,p.stderr,flush=True);sys.exit(p.returncode)
