"""Real stored graph over authenticated loopback HTTP MCP, no analysis/embedding."""
import asyncio,json,os,socket,sys,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
for key in list(os.environ):
 if key.lower() in ('http_proxy','https_proxy','all_proxy'):os.environ.pop(key)
from lct.common import config,canonical
from lct.neo4j_graph import Neo4jGraph,load_snapshot
SIZES=[];READS=[]
def check(value,description):
 if not value:raise AssertionError(description)
async def mcp_check(uri, user, password, database, namespace, version,
                    snapshot, by_kind, source_id, expected_rel):
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from lct.neo4j_mcp import create_app
    from unittest.mock import patch

    class Verifier:
        async def verify_token(self, token):
            if token != "local-business-only":
                return None
            return AccessToken(token=token, client_id="local-acceptance",
                expires_at=4102444800, scopes=["graph:read"], resource=resource)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    resource = base + "/mcp"
    settings = AuthSettings(issuer_url="https://issuer.example.invalid",
        resource_server_url=resource, validate_token_resource=True, required_scopes=["graph:read"])
    original_info = Neo4jGraph.snapshot_info
    info_calls = []

    def counted_info(graph, ns, v):
        info_calls.append((ns, v))
        return original_info(graph, ns, v)

    # The HTTP app must initialize from the small fingerprint marker alone.
    spy = patch.object(Neo4jGraph, "snapshot_info", counted_info)
    spy.start()
    app = create_app(uri=uri, user=user, password=password, database=database,
        namespace=namespace, version=version, token_verifier=Verifier(), auth=settings,
        allowed_host=f"127.0.0.1:{port}", allowed_origin=base)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.05)
        check(server.started, "MCP server startup")
        check(not info_calls, "MCP startup hydrated full status before graph_status")
        async with httpx.AsyncClient() as client:
            response = await client.post(resource, json={})
            check(response.status_code == 401, "unauthenticated MCP request")
        async with streamablehttp_client(resource, headers={
            "Authorization": "Bearer local-business-only", "Origin": base,
        }) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                check({t.name for t in tools.tools} ==
                      {"graph_status", "snapshot_evidence", "list_nodes", "get_nodes", "get_relations"}, "MCP tool set")
                check(all(t.annotations.readOnlyHint for t in tools.tools), "MCP read-only hints")

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    check(not result.isError, f"MCP {name} returned an error")
                    SIZES.append(dict(tool=name,bytes=len(result.model_dump_json().encode())))
                    check(SIZES[-1]["bytes"]<262144,"serialized reply budget")
                    payload = result.structuredContent
                    if payload is None:
                        payload = json.loads(next(c.text for c in result.content if c.type == "text"))
                    check((payload["namespace"], payload["version"], payload["fingerprint"]) ==
                          (namespace, version, snapshot["fingerprint"]), "MCP scope")
                    return payload["data"]

                status = await call("graph_status", {})
                check(not info_calls, "graph_status must not hydrate evidence")
                await call("graph_status", {})
                check((status["nodes"], status["edges"]) ==
                      (len(snapshot["nodes"]), len(snapshot["edges"])), "MCP graph counts")
                evidence = await call("snapshot_evidence", {"kind":"graph"})
                check(evidence["fragment"] and evidence["has_more"], "explicit evidence fragment")
                for kind, node in by_kind.items():
                    listed = await call("list_nodes", {"kind": kind,
                        "repository": node["repository"], "limit": 1})
                    check(listed["nodes"][0]["kind"] == kind, "MCP filter")
                selected = await call("get_nodes", {"ids": [n["node_id"] for n in by_kind.values()]})
                check(selected["nodes"] == list(by_kind.values()), "MCP selected raw nodes")
                rel = await call("get_relations", {"ids": [source_id], "types": ["CALLS"],
                    "direction": "out", "limit": 5000})
                all_edges=list(rel["edges"])
                while rel["has_more"]:
                    rel=await call("get_relations", {"ids":[source_id],"types":["CALLS"],"direction":"out","limit":5000,"cursor":rel["next_cursor"]})
                    all_edges.extend(rel["edges"])
                check(all_edges==expected_rel, "MCP raw relations and UNKNOWN")
                first=await call("list_nodes", {"kind":"function","limit":5000})
                second=await call("list_nodes", {"kind":"function","limit":5000,"cursor":first["next_cursor"]})
                check(first["has_more"] and second["nodes"][0]["node_id"]>first["nodes"][-1]["node_id"], "node page continuation")
                wrong = await session.call_tool("get_nodes", {"ids": [source_id],
                    "namespace": "wrong", "version": "wrong"})
                if not wrong.isError:
                    payload = wrong.structuredContent or json.loads(next(
                        c.text for c in wrong.content if c.type == "text"))
                    check(payload["namespace"] == namespace and payload["version"] == version,
                          "MCP caller changed scope")
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=15)
        finally:
            spy.stop()

def main():
 c=config('/tmp/lct-query-repair-restored/config.json');v=json.loads((Path(c['data'])/'current.json').read_text())['version'];snap=load_snapshot(c,v)
 args=[os.environ['LCT_TEST_NEO4J_'+k] for k in ('URI','USER','PASSWORD','DATABASE')]
 with Neo4jGraph(*args) as g:
  with g.driver.session(database=args[3]) as db:
   row=db.run('MATCH(s:LCTSnapshot {complete:true,fingerprint:$f}) RETURN s.namespace AS ns,s.version AS v LIMIT 1',f=snap['fingerprint']).single()
  if row:ns,v=row['ns'],row['v'];imported=False
  else:ns='batch3-locality-real-20261029';g.import_snapshot(ns,v,snap);imported=True
  for _ in range(2):
   st=g.snapshot_summary(ns,v);assert st['nodes']==5957 and st['edges']==42492
 bykind={k:next(n for n in snap['nodes'] if n['kind']==k) for k in ('module','class','function')}
 counts=collections.Counter(e['source'] for e in snap['edges'] if e['kind']=='CALLS');ids={n['node_id'] for n in snap['nodes']}
 source=next(e['source'] for e in snap['edges'] if e['kind']=='CALLS' and e.get('unknown_origin') and e['source'] in ids and counts[e['source']]<100)
 expected=sorted([e for e in snap['edges'] if e['source']==source and e['kind']=='CALLS'],key=lambda e:e['edge_id'])
 original=Neo4jGraph._read
 def measured(self,namespace,version,query,**params):
  fp,rows=original(self,namespace,version,query,**params)
  READS.append(dict(query=query,rows=len(rows),decoded_bytes=len(canonical([dict(r) for r in rows]).encode())))
  return fp,rows
 Neo4jGraph._read=measured
 try:asyncio.run(mcp_check(*args,ns,v,snap,bykind,source,expected))
 finally:Neo4jGraph._read=original
 out=dict(status='PASS',namespace=ns,neo4j_version=v,index_version=snap['version'],fingerprint=snap['fingerprint'],imported_existing_parsed_graph=imported,parsed_sources=False,paid_requests=0,mcp_sizes=SIZES,reads=READS)
 (ROOT/'review/query-locality-repair/real-neo4j.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
