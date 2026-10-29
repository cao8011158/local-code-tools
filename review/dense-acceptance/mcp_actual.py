"""Actual restored-capable stdio MCP checks, using cached real query vectors only."""
import asyncio,json,sys,hashlib
from pathlib import Path
from datetime import timedelta
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client,get_default_environment
async def main():
 root=Path(sys.argv[1]);cfg=Path(sys.argv[2]);out=Path(sys.argv[3]);env=get_default_environment();env.pop('VOYAGE_API_KEY',None)
 params=StdioServerParameters(command=sys.executable,args=[str(root/'local_code_tools.py'),'--config',str(cfg),'mcp'],cwd=str(root),env=env)
 c=json.loads(cfg.read_text());ledger=Path(c['data'])/'ledger.json';before=ledger.read_bytes()
 with out.with_suffix('.stderr.log').open('w') as err:
  async with stdio_client(params,errlog=err) as (read,write):
   async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=60)) as session:
    await session.initialize();listed=await session.list_tools();calls=[]
    async def call(name,**args):
     r=await session.call_tool(name,args);assert not r.isError,name
     calls.append(name);return r.structuredContent or json.loads(next(x.text for x in r.content if x.type=='text'))
    status=await call('index_status');assert status['status']=='ready' and status['dense_ready'];v=status['version']
    result=await call('search_code',query='ContainerService current_weight',repositories=['trpg-state-machine'],level='function',mode='rrf',limit=1,candidates=20)
    assert result['version']==v and result['results'];nid=result['results'][0]['node_id']
    node=await call('get_nodes',node_ids=[nid],version=v);assert node['nodes'][0]['source_origin']=='indexed_snapshot'
    rel=await call('get_relations',node_ids=[nid],relation_types=['CONTAINS'],direction='in',version=v);assert rel['edges']
    docs=await call('search_docs',query='snapshot',repositories=['agentic-trpg'],limit=2);assert docs['results']
    assert ledger.read_bytes()==before
    evidence=dict(status='PASS',version=v,called=calls,listed=[t.name for t in listed.tools],rank1=result['results'][0]['qualname'],source_origin=node['nodes'][0]['source_origin'],ledger_unchanged=True,credential_passed=False)
    out.write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence))
asyncio.run(main())
