"""Bounded bulk projection against an owned real Neo4j service."""
import os
from uuid import uuid4
from collections import Counter

import pytest

from lct.common import ToolError, canonical, digest
from lct.neo4j_graph import Neo4jGraph, MAX_IMPORT_NODES, MAX_QUERY_IDS
import lct.neo4j_graph as projection


def snapshot(version='bulk-v'):
    nodes = [dict(node_id=f'n{i:04}', kind='function', repository='repo',
                  path='file.py', qualname=f'f{i}', version_id='revision')
             for i in range(1200)]
    edges = []
    for i in range(6000):
        source = f'n{i % 1200:04}'
        target = f'n{(i + 1) % 1200:04}' if i % 5 else ('external' if i % 2 else None)
        edges.append(dict(edge_id=f'e{i:04}', kind='CALLS', source=source,
                          target=target, unknown_origin=i % 5 == 0,
                          complete=i % 5 != 0, site_id=f's{i:04}',
                          source_version_id='revision', target_version_id=None))
    graph = dict(sites=[dict(site_id='shared', unknown_origin=True, complete=False)])
    source = dict(repositories={'repo': 'revision'}, source_fingerprint='source', files=[])
    fingerprint = digest(canonical(dict(nodes=nodes, edges=edges, graph=graph, source=source)))
    return dict(version=version, nodes=nodes, edges=edges, graph=graph,
                source=source, fingerprint=fingerprint)


@pytest.fixture
def graph():
    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('LCT_TEST_NEO4J_URI not set')
    with Neo4jGraph(uri, os.getenv('LCT_TEST_NEO4J_USER', 'neo4j'),
                    os.getenv('LCT_TEST_NEO4J_PASSWORD', 'synthetic-lct-batch1-only'),
                    os.getenv('LCT_TEST_NEO4J_DATABASE', 'neo4j')) as g:
        yield g


def test_bulk_roundtrip_and_query_bound(graph, monkeypatch, tmp_path):
    data = snapshot()
    namespace = 'bulk-' + uuid4().hex
    original = graph.driver
    queries = []

    class Tx:
        def __init__(self, tx): self.tx = tx
        def __enter__(self): self.tx.__enter__(); return self
        def __exit__(self, *exc): return self.tx.__exit__(*exc)
        def run(self, query, **params):
            queries.append((query, len(params.get('rows', []))))
            return self.tx.run(query, **params)

    class Session:
        def __init__(self, session): self.session = session
        def __enter__(self): self.session.__enter__(); return self
        def __exit__(self, *exc): return self.session.__exit__(*exc)
        def run(self, *args, **kwargs): return self.session.run(*args, **kwargs)
        def begin_transaction(self, **kwargs):
            assert kwargs['timeout'] == projection.IMPORT_TIMEOUT_SECONDS
            return Tx(self.session.begin_transaction(**kwargs))

    class Driver:
        def session(self, **kwargs): return Session(original.session(**kwargs))

    graph.driver = Driver()
    result = graph.import_snapshot(namespace, data['version'], data)
    graph.driver = original
    assert (result['nodes'], result['edges'], result['already_present']) == (1200, 6000, False)
    # Each bounded batch now commits independently with two fenced marker statements.
    assert len(queries) < 150
    chunks = [size for _, size in queries if size]
    assert sum(chunks) == 1200 + 6000 + 6000 + 601 + 2
    assert max(chunks) <= 500
    assert graph.snapshot_info(namespace, 'bulk-v')['graph'] == data['graph']
    page = graph.list_nodes(namespace, 'bulk-v', limit=5000)
    listed = list(page['nodes'])
    while page['has_more']:
        page = graph.list_nodes(namespace, 'bulk-v', limit=5000, cursor=page['next_cursor'])
        listed.extend(page['nodes'])
    assert listed == data['nodes']
    ids = [n['node_id'] for n in data['nodes'][:500]]
    cursor, selected = 0, []
    while True:
        page = graph.get_nodes_page(namespace, 'bulk-v', ids, cursor)
        selected.extend(page['nodes'])
        if not page['has_more']:
            break
        cursor = page['next_cursor']
    assert selected == data['nodes'][:500]
    with pytest.raises(ToolError, match='at most 500'):
        graph.get_nodes(namespace, 'bulk-v', [n['node_id'] for n in data['nodes'][:MAX_QUERY_IDS + 1]])
    with graph.driver.session(database=graph.database) as session:
        rows = session.run('MATCH (e:LCTEdge {namespace:$namespace, version:$version}) '
                           'RETURN e.raw_json AS raw, e.internal AS internal ORDER BY e.edge_id',
                           namespace=namespace, version='bulk-v')
        actual = [(row['raw'], row['internal']) for row in rows]
        assert [row[0] for row in actual] == [canonical(e) for e in data['edges']]
        assert Counter(row[1] for row in actual) == {True: 4800, False: 1200}
        assert session.run('MATCH (:LCTNode {namespace:$namespace, version:$version})-[r:CALLS]->() '
                           'RETURN count(r) AS c', namespace=namespace,
                           version='bulk-v').single()['c'] == 6000
    assert graph.import_snapshot(namespace, 'bulk-v', data)['already_present']
    with pytest.raises(ToolError, match='different content'):
        changed = dict(data, source={'changed': True})
        changed['fingerprint'] = digest(canonical(dict(nodes=data['nodes'], edges=data['edges'],
                                                       graph=data['graph'], source=changed['source'])))
        graph.import_snapshot(namespace, 'bulk-v', changed)


def test_failure_after_edge_batch_is_hidden_and_retry_cleans(graph, tmp_path):
    data = snapshot()
    namespace = 'failed-' + uuid4().hex
    original = graph.driver
    completed = 0

    class Tx:
        def __init__(self, tx): self.tx = tx
        def __enter__(self): self.tx.__enter__(); return self
        def __exit__(self, *exc): return self.tx.__exit__(*exc)
        def run(self, query, **params):
            nonlocal completed
            if 'CREATE (e:LCTEdge' in query:
                completed += 1
                if completed == 2:
                    raise RuntimeError('injected after first edge chunk')
            return self.tx.run(query, **params)

    class Session:
        def __init__(self, session): self.session = session
        def __enter__(self): self.session.__enter__(); return self
        def __exit__(self, *exc): return self.session.__exit__(*exc)
        def run(self, *args, **kwargs): return self.session.run(*args, **kwargs)
        def begin_transaction(self, **kwargs): return Tx(self.session.begin_transaction(**kwargs))

    class Driver:
        def session(self, **kwargs): return Session(original.session(**kwargs))

    graph.driver = Driver()
    with pytest.raises(RuntimeError, match='injected'):
        graph.import_snapshot(namespace, 'bulk-v', data)
    graph.driver = original
    assert completed == 2
    with pytest.raises(ToolError, match='missing'):
        graph.snapshot_info(namespace, 'bulk-v')
    with original.session(database=graph.database) as session:
        assert session.run('MATCH (n:LCTNode {namespace:$ns, version:$v}) RETURN count(n) AS c',
                           ns=namespace, v='bulk-v').single()['c'] == 1200
        assert session.run('MATCH (s:LCTSnapshot {namespace:$ns, version:$v}) '
                           'RETURN s.complete AS complete', ns=namespace,
                           v='bulk-v').single()['complete'] is False
    assert graph.import_snapshot(namespace, 'bulk-v', data)['already_present'] is False
    assert graph.snapshot_info(namespace, 'bulk-v')['graph'] == data['graph']


def test_capacity_rejection_before_publication(graph, monkeypatch, tmp_path):
    data = snapshot()
    namespace = 'limits-' + uuid4().hex
    monkeypatch.setattr(projection, 'MAX_IMPORT_NODES', 1199)
    with pytest.raises(ToolError, match='limit exceeded'):
        graph.import_snapshot(namespace, 'bulk-v', data)
    monkeypatch.setattr(projection, 'MAX_IMPORT_NODES', MAX_IMPORT_NODES)
    monkeypatch.setattr(projection, 'MAX_IMPORT_EDGES', 5999)
    with pytest.raises(ToolError, match='limit exceeded'):
        graph.import_snapshot(namespace, 'bulk-v', data)
    monkeypatch.setattr(projection, 'MAX_IMPORT_EDGES', 500_000)
    monkeypatch.setattr(projection, 'MAX_SNAPSHOT_BYTES', 100)
    with pytest.raises(ToolError, match='128 MiB'):
        graph.import_snapshot(namespace, 'bulk-v', data)
    with pytest.raises(ToolError, match='missing'):
        graph.snapshot_info(namespace, 'bulk-v')
