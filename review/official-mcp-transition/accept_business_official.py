"""Owned official MCP acceptance against migrated business projection and SQLite oracle."""
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from lct.neo4j_graph import Neo4jGraph
from lct.official_mcp import read_cypher_requests, node_read_cypher_requests
from lct.common import canonical

NS = 'batch3-real-staged-20261029-7a235bf36f'
VERSION = '20261029T111748-7a235bf36f'
FP = 'db11a1db19ed3f524ba8309184ce6ccc27f44531830f83a0a467736d5150d568'
CATALOG = Path('/tmp/lct-b3-isolated-v2-20261029/data/versions') / VERSION / 'catalog.sqlite'
assert CATALOG.is_file()
with sqlite3.connect(CATALOG.as_uri() + '?mode=ro', uri=True) as db:
    all_edges = [json.loads(r[0]) for r in db.execute('SELECT data FROM edges ORDER BY edge_id')]
    code_ids = {r[0] for r in db.execute('SELECT node_id FROM nodes')}
    sample = next(e for e in all_edges if e.get('source') in code_ids and e.get('target') is None)
    node_id = sample['source']
    expected = [e for e in all_edges if e.get('source') == node_id and e['kind'] == 'CALLS']
    assert expected and any(e.get('target') is None for e in expected)
    with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'], os.environ['LCT_TEST_NEO4J_USER'],
                    os.environ['LCT_TEST_NEO4J_PASSWORD'], os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
        assert graph.snapshot_fingerprint(NS, VERSION) == FP
        result = graph.get_relations(NS, VERSION, [node_id], ['CALLS'], 'out', limit=5000)
        assert result['edges'] == expected
        assert not result['has_more']

async def check():
    env = dict(os.environ, NEO4J_MCP_URI=os.environ['LCT_TEST_NEO4J_URI'],
               NEO4J_MCP_USERNAME=os.environ['LCT_TEST_NEO4J_USER'],
               NEO4J_MCP_PASSWORD=os.environ['LCT_TEST_NEO4J_PASSWORD'],
               NEO4J_MCP_DATABASE=os.environ['LCT_TEST_NEO4J_DATABASE'],
               NEO4J_MCP_READ_ONLY='true', NEO4J_MCP_TELEMETRY='false')
    server = StdioServerParameters(command='uvx', args=['--from','neo4j-mcp-server==1.6.1',
                                    'neo4j-mcp-server'], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert 'read-cypher' in tools and 'write-cypher' not in tools
            async def call(request):
                result = await session.call_tool(**request)
                assert not result.isError, result
                return result.structuredContent or json.loads(next(
                    c.text for c in result.content if c.type == 'text'))
            collected, cursor, boundary_ids = [], None, []
            while True:
                marker_request, relation_request = read_cypher_requests(NS, VERSION,
                    [node_id], FP, ['CALLS'], 'out', limit=16, cursor=cursor)
                marker = await call(marker_request)
                assert len(marker) == 1 and marker[0]['fingerprint'] == FP
                rows = await call(relation_request)
                for row in rows[:16]:
                    assert row['fingerprint'] == FP and not row['raw_too_large']
                    collected.append(json.loads(row['raw']))
                    if row['target_boundary_id']:
                        boundary_ids.append(row['target_boundary_id'])
                if len(rows) <= 16:
                    break
                cursor = rows[15]['id']
            assert collected == expected
            assert boundary_ids
            request = node_read_cypher_requests(NS, VERSION, [boundary_ids[0]], FP,
                                                boundary=True)[1]
            boundary = (await call(request))[0]
            assert boundary['boundary_id'] == boundary_ids[0]
            assert boundary['category'] in ('external','unresolved')
            return dict(tools=sorted(tools), sample_node=node_id, matching_calls=len(collected),
                        boundary_sample=boundary['boundary_id'], marker=marker[0],
                        sqlite_catalog=str(CATALOG))
print(canonical(asyncio.run(check())))
