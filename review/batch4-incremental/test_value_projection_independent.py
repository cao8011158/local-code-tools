"""Root-authored projection checks; build captured source, then query actual Neo4j."""
import asyncio
from copy import deepcopy
import json
import os
import uuid

import pytest

from lct.common import ToolError, canonical
from lct.neo4j_graph import Neo4jGraph, load_snapshot
from lct.storage import build
from tests.synthetic_support import initialize

SERVICE = pytest.mark.skipif(not os.getenv('LCT_TEST_NEO4J_URI'), reason='owned Neo4j required')


def fixture(tmp_path):
    config, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/a.py').write_text("def first(): pass\ndef second(): pass\nregistry={'go':first}\nregistry['go']=second\n")
    (repo / 'src/b.py').write_text("from a import registry as imported\nalias=imported\ndef run():\n    local=alias\n    local['go']()\ndef missing():\n    alias['future']()\n")
    built = build(config, offline=True, lexical_only=True)
    return config, repo, load_snapshot(config, built['version'])


def connection():
    return Neo4jGraph(*(os.environ[k] for k in ('LCT_TEST_NEO4J_URI', 'LCT_TEST_NEO4J_USER',
                                               'LCT_TEST_NEO4J_PASSWORD', 'LCT_TEST_NEO4J_DATABASE')))


def run_requests(graph, requests):
    with graph.driver.session(database=graph.database) as session:
        return [[dict(row) for row in session.run(request['arguments']['query'],**request['arguments']['params'])]
                for request in requests]


@pytest.mark.parametrize('array', ['nodes', 'edges', 'reads'])
def test_each_value_array_is_bound_by_fingerprint(tmp_path, array):
    _, _, snapshot = fixture(tmp_path)
    assert snapshot['projection_schema'] == 'native-value-v3'
    forged = deepcopy(snapshot)
    record = forged['value_flow'][array][0]
    record['name' if array == 'nodes' else 'target' if array == 'edges' else 'consumer_path'] = 'tampered'
    graph = Neo4jGraph.__new__(Neo4jGraph)
    with pytest.raises(ToolError):
        graph.import_snapshot('independent-no-driver', snapshot['version'], forged)


@SERVICE
def test_native_aliases_subscriptions_old_views_and_code_domain(tmp_path):
    from lct.official_mcp import value_node_read_cypher_requests, value_read_cypher_requests
    config, repo, first = fixture(tmp_path)
    namespace = 'root-value-' + uuid.uuid4().hex
    value = first['value_flow']
    with connection() as graph:
        graph.import_snapshot(namespace, first['version'], first)
        marker = graph.snapshot_summary(namespace, first['version'])
        assert len(canonical(marker).encode()) < 8192
        assert marker['projection_schema'] == 'native-value-v3'
        with graph.driver.session(database=graph.database) as session:
            raw = [json.loads(r['raw']) for r in session.run(
                'MATCH(n:LCTValue {namespace:$ns,version:$v}) RETURN n.raw_json AS raw',
                ns=namespace, v=first['version'])]
            assert sorted(raw, key=lambda x: x['id']) == sorted(value['nodes'], key=lambda x:x['id'])
            native = list(session.run('MATCH(a)-[r {namespace:$ns,version:$v}]->(b) '
                'WHERE r.value_edge_id IS NOT NULL RETURN coalesce(a.value_id,a.node_id) AS s, '
                'type(r) AS k,coalesce(b.value_id,b.node_id) AS t',ns=namespace,v=first['version']))
            assert {(r['s'],r['k'],r['t']) for r in native} == {
                (e['source'],e['kind'],e['target']) for e in value['edges']}
        negative = next(n for n in value['nodes'] if n['kind']=='entry' and n['key']=='future')
        assert negative['present'] is False
        req = value_node_read_cypher_requests(namespace,first['version'],[negative['id']],first['fingerprint'])
        assert json.loads(run_requests(graph,req)[1][0]['raw']) == negative
        subscriptions = run_requests(graph,value_read_cypher_requests(namespace,first['version'],
            [negative['id']],first['fingerprint'],types=['READS'],direction='in'))[1]
        assert len(subscriptions)==1
        subscription = json.loads(subscriptions[0]['raw'])
        expected = next(r for r in value['reads'] if r['entry']==negative['id'])
        assert subscription['consumer_repository']==expected['consumer_repository']
        assert subscription['consumer_path']==expected['consumer_path']
        for function in (n for n in first['nodes'] if n['kind']=='function'):
            code_edges=graph.get_relations(namespace,first['version'],[function['node_id']])['edges']
            assert all(e['kind'] not in {'VALUE','POSSIBLE_CALLS'} for e in code_edges)
        old_raw = canonical(sorted(raw,key=lambda x:x['id']))
        (repo/'src/a.py').write_text((repo/'src/a.py').read_text()+"registry['future']=second\n")
        updated=build(config,offline=True,lexical_only=True)
        second=load_snapshot(config,updated['version'])
        graph.import_snapshot(namespace,second['version'],second)
        assert canonical([json.loads(r['raw']) for r in run_requests(graph,
            value_node_read_cypher_requests(namespace,first['version'],
                [n['id'] for n in value['nodes']][:16],first['fingerprint']))[1]])
        with graph.driver.session(database=graph.database) as session:
            assert canonical(sorted([json.loads(r['raw']) for r in session.run(
                'MATCH(n:LCTValue {namespace:$ns,version:$v}) RETURN n.raw_json AS raw',
                ns=namespace,v=first['version'])],key=lambda x:x['id']))==old_raw
        assert run_requests(graph,value_node_read_cypher_requests(namespace,first['version'],
            [negative['id']],second['fingerprint']))==[[],[]]


@SERVICE
def test_failed_value_batch_stays_hidden_and_retries(tmp_path,monkeypatch):
    from lct import neo4j_graph as module
    _,_,snapshot=fixture(tmp_path)
    ns='root-value-failure-'+uuid.uuid4().hex
    actual=module._write
    def fail_after_value(session,scope,owner,query,rows=None,state='writing'):
        actual(session,scope,owner,query,rows,state)
        if 'CREATE (n:LCTValue:' in query:
            raise RuntimeError('root injected after committed value batch')
    with connection() as graph:
        monkeypatch.setattr(module,'_write',fail_after_value)
        with pytest.raises(RuntimeError,match='root injected'):
            graph.import_snapshot(ns,snapshot['version'],snapshot)
        with pytest.raises(ToolError,match='incomplete'):
            graph.snapshot_summary(ns,snapshot['version'])
        monkeypatch.setattr(module,'_write',actual)
        graph.import_snapshot(ns,snapshot['version'],snapshot)
        assert graph.snapshot_summary(ns,snapshot['version'])['projection_schema']=='native-value-v3'
        assert graph.import_snapshot(ns,snapshot['version'],snapshot)['already_present']


@SERVICE
def test_actual_templates_index_plans_and_official_read_only_mcp(tmp_path):
    from lct.official_mcp import value_node_read_cypher_requests,value_read_cypher_requests
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    _,_,snapshot=fixture(tmp_path)
    ns='root-value-profile-'+uuid.uuid4().hex
    read=next(n for n in snapshot['value_flow']['nodes'] if n['kind']=='read')
    requests=value_read_cypher_requests(ns,snapshot['version'],[read['id']],snapshot['fingerprint'])
    reports=[]
    with connection() as graph:
        graph.import_snapshot(ns,snapshot['version'],snapshot)
        for noise in (0,1000):
            with graph.driver.session(database=graph.database) as session:
                if noise:
                    session.run('UNWIND range(1,$n) AS i CREATE (:LCTValue '
                        '{namespace:$ns,version:$v,value_id:toString(i),raw_json:$big})',
                        n=noise,ns=ns+'-noise',v=snapshot['version'],big='x'*2048).consume()
                group=[]
                for request in requests:
                    args=request['arguments']
                    explain=session.run('EXPLAIN '+args['query'],**args['params']).consume()
                    assert explain.plan
                    measures=[]
                    for temperature in ('cold','repeat'):
                        result=session.run('PROFILE '+args['query'],**args['params'])
                        rows=[dict(row) for row in result];summary=result.consume()
                        ops=[]
                        def walk(plan):
                            ops.append(dict(operator=plan['operatorType'],rows=plan.get('rows',0),
                                            db_hits=plan.get('dbHits',0)))
                            for child in plan.get('children',[]):walk(child)
                        walk(summary.profile)
                        assert any('IndexSeek' in op['operator'] for op in ops),ops
                        assert not any('AllNodesScan' in op['operator'] or 'NodeByLabelScan' in op['operator']
                                       for op in ops),ops
                        measures.append(dict(temperature=temperature,rows=len(rows),
                            bytes=len(canonical(rows).encode()),db_hits=sum(op['db_hits'] for op in ops),operators=ops))
                    group.append(measures)
                reports.append(dict(unrelated=noise,queries=group))
        assert [[m['db_hits'] for m in q] for q in reports[0]['queries']]==[
            [m['db_hits'] for m in q] for q in reports[1]['queries']],reports
    async def verify_mcp():
        env=dict(os.environ,NEO4J_MCP_URI=os.environ['LCT_TEST_NEO4J_URI'],
            NEO4J_MCP_USERNAME=os.environ['LCT_TEST_NEO4J_USER'],
            NEO4J_MCP_PASSWORD=os.environ['LCT_TEST_NEO4J_PASSWORD'],
            NEO4J_MCP_DATABASE=os.environ['LCT_TEST_NEO4J_DATABASE'],
            NEO4J_MCP_READ_ONLY='true',NEO4J_MCP_TELEMETRY='false')
        server=StdioServerParameters(command='uvx',args=['--offline','--from',
            'neo4j-mcp-server==1.6.1','neo4j-mcp-server'],env=env)
        async with stdio_client(server) as (read_stream,write_stream):
            async with ClientSession(read_stream,write_stream) as client:
                await client.initialize()
                tools={t.name for t in (await client.list_tools()).tools}
                assert 'read-cypher' in tools and 'write-cypher' not in tools
                for request in requests+value_node_read_cypher_requests(ns,snapshot['version'],
                        [read['id']],snapshot['fingerprint']):
                    result=await client.call_tool(**request)
                    assert not result.isError,result
                    body=result.structuredContent
                    if body is None:body=json.loads(next(c.text for c in result.content if c.type=='text'))
                    assert body
                    assert len(canonical(body).encode())<65536
                rejected=await client.call_tool('read-cypher',dict(query='CREATE (:ForbiddenRootValueProbe)',params={}))
                assert rejected.isError
    asyncio.run(verify_mcp())
    print('ROOT_VALUE_PROJECTION_PROFILE='+json.dumps(reports,sort_keys=True))
