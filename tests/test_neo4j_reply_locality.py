"""No-service regression for marker reads, byte budgets, and cursor boundaries."""
import json

import pytest

from lct.common import ToolError, canonical
from lct.neo4j_graph import Neo4jGraph, MAX_REPLY_DATA_BYTES


def fake_graph(nodes=(), internal=(), external=()):
    graph = Neo4jGraph.__new__(Neo4jGraph)
    calls = []

    def read(namespace, version, query, **params):
        calls.append((query, params))
        if 's.node_count AS nodes' in query:
            return 'fingerprint', [dict(nodes=len(nodes), edges=len(internal) + len(external),
                                        native_edges=len(internal), chunks=300,
                                        graph_sha256='g', source_sha256='s', storage_format='chunks-v1')]
        if 's.projection_schema AS projection_schema' in query:
            return 'fingerprint', [dict(projection_schema=None)]
        if 's.storage_format AS format' in query:
            return 'fingerprint', [dict(format='chunks-v1')]
        if 'MATCH (c:LCTChunk' in query:
            assert 'c.data AS data' not in query
            return 'fingerprint', [dict(ordinal=0, data='{"sites":', length=9),
                                   dict(ordinal=1, data='[]}', length=3)] if params['ordinal'] == 0 else [
                                       dict(ordinal=1, data='[]}', length=3)]
        if 'n.node_id IN $ids' in query:
            selected = set(params['ids'])
            return 'fingerprint', [dict(id=n['node_id'], raw=canonical(n)) for n in nodes
                                   if n['node_id'] in selected]
        if 'RETURN n.node_id AS id' in query:
            selected = [n for n in nodes if (params['cursor'] is None or
                                             n['node_id'] > params['cursor'])]
            return 'fingerprint', [dict(id=n['node_id'], raw=canonical(n)) for n in
                                   selected[:params['fetch']]]
        if 'RETURN e.edge_id AS id' in query:
            source = external if 'e.internal=false' in query else internal
            selected = [e for e in source if params['cursor'] is None or
                        e['edge_id'] > params['cursor']]
            return 'fingerprint', [dict(id=e['edge_id'], raw=canonical(e)) for e in
                                   selected[:params['fetch']]]
        raise AssertionError(query)

    graph._read = read
    return graph, calls


def test_summary_cold_warm_and_evidence_are_local():
    graph, calls = fake_graph()
    for _ in range(2):
        status = graph.snapshot_summary('n', 'v')
        assert status['chunks'] == 300
        assert 'sites' not in status
    assert len(calls) == 2
    assert all('LCTChunk' not in query and 'graph_json' not in query for query, _ in calls)
    first = graph.snapshot_evidence('n', 'v', 'graph')
    second = graph.snapshot_evidence('n', 'v', 'graph', first['next_cursor'])
    assert json.loads(first['fragment'] + second['fragment']) == {'sites': []}
    assert not second['has_more']


def test_node_and_relation_pages_preserve_order_and_unknown_fields():
    nodes = [dict(node_id=f'n{i:02}', raw='x' * 8000) for i in range(23)]
    internal = [dict(edge_id=f'e{i:02}', status='UNKNOWN', complete=False,
                     unknown_origin='dynamic', reason='unresolved') for i in range(0, 25, 2)]
    external = [dict(edge_id=f'e{i:02}', status='UNKNOWN', complete=False,
                     unknown_origin='external', reason='external endpoint') for i in range(1, 25, 2)]
    graph, calls = fake_graph(nodes, internal, external)
    listed, cursor = [], None
    while True:
        page = graph.list_nodes('n', 'v', limit=100, cursor=cursor)
        assert len(canonical(page).encode()) <= MAX_REPLY_DATA_BYTES
        listed.extend(page['nodes'])
        if not page['has_more']:
            break
        cursor = page['next_cursor']
    assert listed == nodes
    ids = ['absent', *[n['node_id'] for n in nodes], 'missing']
    got, cursor = [], 0
    while True:
        page = graph.get_nodes_page('n', 'v', ids, cursor)
        got.extend(page['nodes'])
        if not page['has_more']:
            break
        cursor = page['next_cursor']
    assert got == nodes
    with pytest.raises(ToolError, match='use get_nodes_page'):
        graph.get_nodes('n', 'v', ids)
    edges, cursor = [], None
    while True:
        page = graph.get_relations('n', 'v', ['n00'], limit=100, cursor=cursor)
        edges.extend(page['edges'])
        if not page['has_more']:
            break
        cursor = page['next_cursor']
    assert edges == sorted(internal + external, key=lambda e: e['edge_id'])
    assert all(e['reason'] and e['complete'] is False for e in edges)
    assert max(p['fetch'] for q, p in calls if 'fetch' in p) <= 17


def test_oversized_single_item_is_explicit():
    graph, _ = fake_graph([dict(node_id='one', evidence='x' * MAX_REPLY_DATA_BYTES)])
    with pytest.raises(ToolError, match='Single graph record'):
        graph.list_nodes('n', 'v')
    with pytest.raises(ToolError, match='Single graph record'):
        graph.get_nodes_page('n', 'v', ['one'])
