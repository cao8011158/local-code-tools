"""Real official Neo4j MCP 1.6.1 against owned Neo4j 5.26; no embedding/import of user data."""
import asyncio
import json
import os
import uuid

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.shared.exceptions import McpError
from mcp.client.stdio import stdio_client

from lct.common import canonical, digest
from lct.neo4j_graph import Neo4jGraph
from lct.official_mcp import read_cypher_requests, node_read_cypher_requests


@pytest.mark.skipif(not os.environ.get('LCT_TEST_NEO4J_URI'), reason='owned Neo4j URI required')
def test_official_read_cypher_known_node():
    namespace = 'official-test-' + uuid.uuid4().hex
    version = 'fixture-v1'
    nodes = [dict(node_id=n, kind='function', repository='r') for n in ('a', 'b')]
    edges = [dict(edge_id=str(i), kind='CALLS', source=source, target=target,
                  status='UNKNOWN', complete=False, unknown_origin='dynamic',
                  reason='preserved') for i, (source, target) in enumerate(
                      [('a', 'b'), ('a', 'a'), ('a', 'external:pkg'),
                       ('external:pkg', 'a'), ('a', None)])]
    snapshot = dict(version=version, nodes=nodes, edges=edges, graph={'sites': []},
                    source={'repositories': []})
    snapshot['fingerprint'] = digest(canonical({k: snapshot[k] for k in
                                               ('nodes', 'edges', 'graph', 'source')}))
    with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'], os.environ['LCT_TEST_NEO4J_USER'],
                    os.environ['LCT_TEST_NEO4J_PASSWORD'], os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
        graph.maintain_indexes()
        graph.maintain_indexes()  # Idempotent offline maintenance.
        graph.import_snapshot(namespace, version, snapshot)
        expected = graph.get_relations(namespace, version, ['a'])['edges']

    async def check():
        env = dict(os.environ, NEO4J_MCP_URI=os.environ['LCT_TEST_NEO4J_URI'],
                   NEO4J_MCP_USERNAME=os.environ['LCT_TEST_NEO4J_USER'],
                   NEO4J_MCP_PASSWORD=os.environ['LCT_TEST_NEO4J_PASSWORD'],
                   NEO4J_MCP_DATABASE=os.environ['LCT_TEST_NEO4J_DATABASE'],
                   NEO4J_MCP_READ_ONLY='true', NEO4J_MCP_TELEMETRY='false')
        server = StdioServerParameters(command='uvx', args=['--from',
            'neo4j-mcp-server==1.6.1', 'neo4j-mcp-server'], env=env)
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                assert 'read-cypher' in tools and 'write-cypher' not in tools, tools
                async def call(request):
                    result = await session.call_tool(**request)
                    assert not result.isError, result
                    payload = result.structuredContent
                    if payload is None:
                        payload = json.loads(next(c.text for c in result.content if c.type == 'text'))
                    return payload

                for direction in ('in', 'out', 'both'):
                    for ids in (['a'], ['a', 'external:pkg']):
                        expected_edges = [e for e in edges if any(
                            (e['source'] == nid if direction == 'out' else
                             e['target'] == nid if direction == 'in' else
                             nid in (e['source'], e['target'])) for nid in ids)]
                        result_edges, cursor = [], None
                        while True:
                            requests = read_cypher_requests(namespace, version, ids,
                                snapshot['fingerprint'], direction=direction, limit=2,
                                cursor=cursor)
                            marker = await call(requests[0])
                            assert marker == [dict(fingerprint=snapshot['fingerprint'],
                                nodes=2, edges=5, boundary_count=2)]
                            page = await call(requests[1])
                            result_edges.extend(json.loads(row['raw']) for row in page[:2])
                            assert all(row['fingerprint'] == snapshot['fingerprint'] for row in page)
                            if len(page) <= 2:
                                break
                            cursor = page[1]['id']
                        assert result_edges == expected_edges
                node_requests = node_read_cypher_requests(namespace, version, ['a'],
                    snapshot['fingerprint'])
                assert json.loads((await call(node_requests[1]))[0]['raw']) == nodes[0]
                boundary_id = 'unresolved:4:target'
                boundary_requests = node_read_cypher_requests(namespace, version,
                    [boundary_id], snapshot['fingerprint'], boundary=True)
                assert (await call(boundary_requests[1]))[0]['boundary_id'] == boundary_id
                wrong = read_cypher_requests(namespace, version, ['a'], '0'*64)
                assert await call(wrong[0]) == []
                assert await call(wrong[1]) == []
                # The official server rejects writes even through its read-cypher tool.
                mutation = await session.call_tool('read-cypher', {
                    'query': 'CREATE (n:LCTForbiddenProbe {id:$id}) RETURN n',
                    'params': {'id': namespace}})
                assert mutation.isError
                # The official server does not expose mutation tools in READ_ONLY mode.
                with pytest.raises(McpError, match='not found'):
                    await session.call_tool('write-cypher', {'query': 'RETURN 1'})
                return True

    assert asyncio.run(check())
