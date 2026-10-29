"""Resume only local HTTP MCP acceptance after an environment-only client failure."""
import asyncio,collections,json,os,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
for name in ('ALL_PROXY','all_proxy','HTTP_PROXY','http_proxy','HTTPS_PROXY','https_proxy'):
 os.environ.pop(name,None)
from accept_business_graph import mcp_check
from lct.common import config
from lct.neo4j_graph import load_snapshot,Neo4jGraph
c=config('/tmp/lct-b3-isolated-v2-20261029/config.json');version='20261029T111748-7a235bf36f';ns='batch3-real-staged-20261029-7a235bf36f'
start=time.monotonic();snapshot=load_snapshot(c,version);nodes=snapshot['nodes'];edges=snapshot['edges'];ids={n['node_id'] for n in nodes}
by_kind={k:next(n for n in nodes if n['kind']==k) for k in ('module','class','function')}
counts=collections.Counter(e.get('source') for e in edges if e['kind']=='CALLS')
source=next(e['source'] for e in edges if e['kind']=='CALLS' and e.get('unknown_origin') and e.get('source') in ids and counts[e['source']]<100)
expected=sorted((e for e in edges if e['kind']=='CALLS' and e.get('source')==source),key=lambda e:e['edge_id'])
uri=os.environ['LCT_TEST_NEO4J_URI'];user=os.environ['LCT_TEST_NEO4J_USER'];password=os.environ['LCT_TEST_NEO4J_PASSWORD'];database=os.environ['LCT_TEST_NEO4J_DATABASE']
r={'version':version,'namespace':ns,'only_mcp_retried':True,'reimport':False,'paid_requests':0}
try:
 with Neo4jGraph(uri,user,password,database) as db:assert db.snapshot_fingerprint(ns,version)==snapshot['fingerprint']
 asyncio.run(mcp_check(uri,user,password,database,ns,version,snapshot,by_kind,source,expected))
 r['result']='PASS'
except BaseException as error:
 r.update(result='FAIL',error=type(error).__name__+': '+str(error));raise
finally:
 r['seconds']=time.monotonic()-start;(root/'review/business-resume/mcp-acceptance.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
