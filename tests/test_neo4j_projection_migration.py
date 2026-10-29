"""In-place v1 maintenance and fail-closed resume on an owned Neo4j service."""
import os
import uuid

import pytest

from lct.common import ToolError, canonical, digest
from lct.neo4j_graph import Neo4jGraph


@pytest.mark.skipif(not os.environ.get('LCT_TEST_NEO4J_URI'), reason='owned Neo4j URI required')
def test_migrate_legacy_projection_retry(monkeypatch):
    from lct import neo4j_graph as module
    namespace = 'migrate-test-' + uuid.uuid4().hex
    version = 'v1'
    nodes = [dict(node_id=n, kind='function', repository='r') for n in ('a', 'b')]
    edges = [dict(edge_id=str(i), kind='CALLS', source=s, target=t,
                  complete=False, status='UNKNOWN', unknown_origin='dynamic', reason='keep')
             for i, (s, t) in enumerate([('a','b'), ('a',None), ('a','external:x'),
                                          ('external:x','a'), ('a',None)])]
    snapshot = dict(version=version, nodes=nodes, edges=edges, graph={'sites': []},
                    source={'repositories': []})
    snapshot['fingerprint'] = digest(canonical({k:snapshot[k] for k in
                                               ('nodes','edges','graph','source')}))
    with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'], os.environ['LCT_TEST_NEO4J_USER'],
                    os.environ['LCT_TEST_NEO4J_PASSWORD'], os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
        graph.import_snapshot(namespace, version, snapshot)
        with graph.driver.session(database=graph.database) as session:
            scope = dict(namespace=namespace, version=version)
            session.run('MATCH (a)-[r {namespace:$namespace,version:$version}]->(b) '
                        'WHERE a:LCTBoundary OR b:LCTBoundary DELETE r', **scope).consume()
            session.run('MATCH (b:LCTBoundary {namespace:$namespace,version:$version}) DETACH DELETE b',
                        **scope).consume()
            session.run('MATCH (e:LCTEdge {namespace:$namespace,version:$version}) '
                        'REMOVE e.source_boundary_id,e.target_boundary_id', **scope).consume()
            session.run('MATCH (s:LCTSnapshot {namespace:$namespace,version:$version}) '
                        'REMOVE s.projection_schema,s.boundary_count '
                        'SET s.native_count=1', **scope).consume()
        assert graph.get_relations(namespace,version,['a'])['edges'] == edges
        orig = module._write
        injected = {'once': True}
        def fail_after_boundary(session, scope, owner, query, rows=None, state='writing'):
            orig(session,scope,owner,query,rows,state)
            if injected['once'] and 'MERGE (b:LCTBoundary' in query:
                injected['once'] = False
                raise RuntimeError('injected interruption after boundary batch')
        monkeypatch.setattr(module, '_write', fail_after_boundary)
        with pytest.raises(RuntimeError, match='injected'):
            graph.migrate_projection(namespace,version,snapshot['fingerprint'])
        with pytest.raises(ToolError, match='missing or incomplete'):
            graph.get_relations(namespace,version,['a'])
        with graph.driver.session(database=graph.database) as session:
            row = session.run('MATCH (s:LCTSnapshot {namespace:$namespace,version:$version}) '
                              'RETURN s.complete AS complete,s.state AS state,s.fingerprint AS fp',
                              **scope).single()
            assert (row['complete'],row['state'],row['fp']) == (False,'failed',snapshot['fingerprint'])
        monkeypatch.setattr(module, '_write', orig)
        result = graph.migrate_projection(namespace,version,snapshot['fingerprint'])
        assert (result['edges'],result['boundaries'],result['already_present']) == (5,3,False)
        assert graph.migrate_projection(namespace,version,snapshot['fingerprint'])['already_present']
        assert graph.get_relations(namespace,version,['a'])['edges'] == edges
        assert graph.get_relations(namespace,version,['external:x'])['edges'] == edges[2:4]
        with graph.driver.session(database=graph.database) as session:
            row = session.run('MATCH (s:LCTSnapshot {namespace:$namespace,version:$version}) '
                              'RETURN s.fingerprint AS fp,s.complete AS complete,s.projection_schema AS schema',
                              **scope).single()
            assert (row['fp'],row['complete'],row['schema']) == (
                snapshot['fingerprint'],True,'native-boundary-v2')
            assert session.run('MATCH (a)-[r {namespace:$namespace,version:$version}]->(b) '
                               'RETURN count(r) AS c',**scope).single()['c'] == 5
            boundaries = list(session.run('MATCH (b:LCTBoundary {namespace:$namespace,version:$version}) '
                                          'RETURN b.boundary_id AS id ORDER BY id', **scope))
            assert [r['id'] for r in boundaries] == [
                'external:external:x','unresolved:1:target','unresolved:4:target']
