"""Adversarial staged-publication checks against an owned Neo4j service."""
import os
from uuid import uuid4

import pytest

from lct.common import ToolError, canonical, digest
import lct.neo4j_graph as projection
from lct.neo4j_graph import Neo4jGraph, _chunks


def sample(version='staged-v', size=0):
    nodes = [dict(node_id='one', kind='function', repository='r', path='p',
                  qualname='q', version_id='rev')]
    edges = [dict(edge_id='boundary', kind='CALLS', source='one', target=None,
                  unknown_origin=True, complete=False),
             dict(edge_id='loop', kind='CALLS', source='one', target='one',
                  unknown_origin=False, complete=True)]
    graph = dict(sites=[dict(site_id='unknown', reason='未解析🧭',
                             unknown_origin=True, complete=False)],
                 padding='汉🧭' * (size // 7))
    source = dict(repositories={'r': 'rev'}, source_fingerprint='rev', files=[])
    fingerprint = digest(canonical(dict(nodes=nodes, edges=edges, graph=graph, source=source)))
    return dict(version=version, nodes=nodes, edges=edges, graph=graph,
                source=source, fingerprint=fingerprint)


@pytest.fixture
def db():
    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('LCT_TEST_NEO4J_URI not set')
    with Neo4jGraph(uri, os.getenv('LCT_TEST_NEO4J_USER', 'neo4j'),
                    os.getenv('LCT_TEST_NEO4J_PASSWORD', 'synthetic-lct-batch1-only'),
                    os.getenv('LCT_TEST_NEO4J_DATABASE', 'neo4j')) as graph:
        yield graph


def test_utf8_chunks_do_not_skip_split_characters():
    text = 'a' * (projection.CHUNK_BYTES - 1) + '🧭汉' * 40
    parts = list(_chunks(text))
    assert len(parts) == 2
    assert ''.join(parts) == text
    assert max(len(part.encode('utf-8')) for part in parts) <= projection.CHUNK_BYTES


def test_eight_megabyte_metadata_roundtrip(db):
    ns = 'large-' + uuid4().hex
    data = sample(size=8 * 1024 * 1024)
    assert len(canonical(data['graph']).encode('utf-8')) > 8 * 1024 * 1024
    db.import_snapshot(ns, data['version'], data)
    assert db.snapshot_info(ns, data['version'])['graph'] == data['graph']
    with db.driver.session(database=db.database) as session:
        rows = list(session.run('MATCH (c:LCTChunk {namespace:$ns, version:$v}) '
                                'RETURN c.data AS data', ns=ns, v=data['version']))
        assert len(rows) > 30
        assert max(len(row['data'].encode('utf-8')) for row in rows) <= projection.CHUNK_BYTES
        marker = session.run('MATCH (s:LCTSnapshot {namespace:$ns, version:$v}) '
                             'RETURN s.graph_json AS old', ns=ns, v=data['version']).single()
        assert marker['old'] is None


@pytest.mark.parametrize('mutation', ['edge', 'chunk', 'extra_relation'])
def test_tampered_candidate_never_publishes_and_retry_restarts(db, monkeypatch, mutation):
    ns = 'tamper-' + uuid4().hex
    data = sample()
    original = projection._verify

    def corrupt_then_verify(session, scope, owner, *args):
        statements = {
            'edge': 'MATCH (e:LCTEdge {namespace:$namespace, version:$version}) '
                    "WHERE e.edge_id='loop' SET e.raw_json='{}'",
            'chunk': 'MATCH (c:LCTChunk {namespace:$namespace, version:$version}) '
                     "WHERE c.kind='graph' AND c.ordinal=0 DELETE c",
            'extra_relation': 'MATCH (n:LCTNode {namespace:$namespace, version:$version}) '
                              'CREATE (n)-[:CALLS {edge_id:"extra", namespace:$namespace, '
                              'version:$version}]->(n)',
        }
        session.run(statements[mutation], **scope).consume()
        return original(session, scope, owner, *args)

    monkeypatch.setattr(projection, '_verify', corrupt_then_verify)
    with pytest.raises(ToolError, match='verification'):
        db.import_snapshot(ns, data['version'], data)
    with pytest.raises(ToolError, match='missing'):
        db.snapshot_info(ns, data['version'])
    monkeypatch.setattr(projection, '_verify', original)
    assert db.import_snapshot(ns, data['version'], data)['already_present'] is False
    assert db.snapshot_info(ns, data['version'])['graph'] == data['graph']


def test_cleanup_rejects_complete_and_active_other_owner(db):
    ns = 'fence-' + uuid4().hex
    data = sample()
    db.import_snapshot(ns, data['version'], data)
    scope = dict(namespace=ns, version=data['version'])
    with db.driver.session(database=db.database) as session:
        with pytest.raises(ToolError, match='ownership lost'):
            projection._cleanup(session, scope, 'not-owner')
    assert db.snapshot_info(ns, data['version'])['nodes'] == 1


def test_expired_owner_is_fenced_on_retry(db):
    ns = 'expired-' + uuid4().hex
    data = sample()
    scope = dict(namespace=ns, version=data['version'])
    with db.driver.session(database=db.database) as session:
        session.run('CREATE (s:LCTSnapshot {namespace:$namespace, version:$version, '
                    "fingerprint:$fingerprint, complete:false, owner:'stale', "
                    "lease_until:0, state:'writing', storage_format:'chunks-v1', "
                    "projection_schema:'native-boundary-v2'})",
                    **scope, fingerprint=data['fingerprint']).consume()
    assert db.import_snapshot(ns, data['version'], data)['already_present'] is False
    with db.driver.session(database=db.database) as session:
        with pytest.raises(ToolError, match='ownership lost'):
            projection._write(session, scope, 'stale', 'RETURN 1')
    assert db.snapshot_info(ns, data['version'])['edges'] == 2


def test_incomplete_old_projection_marker_is_rejected_without_rewrite(db):
    ns = 'old-incomplete-' + uuid4().hex
    data = sample()
    scope = dict(namespace=ns, version=data['version'])
    with db.driver.session(database=db.database) as session:
        session.run('CREATE (s:LCTSnapshot {namespace:$namespace, version:$version, '
                    "fingerprint:$fingerprint, complete:false, owner:'stale', "
                    "lease_until:0, state:'writing', storage_format:'chunks-v1'})",
                    **scope, fingerprint=data['fingerprint']).consume()
        before = session.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                             'RETURN properties(s) AS marker', **scope).single()['marker']

    with pytest.raises(ToolError, match='different projection'):
        db.import_snapshot(ns, data['version'], data)

    with db.driver.session(database=db.database) as session:
        after = session.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                            'RETURN properties(s) AS marker', **scope).single()['marker']
    assert after == before
    with pytest.raises(ToolError, match='missing'):
        db.snapshot_info(ns, data['version'])
