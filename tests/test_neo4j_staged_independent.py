"""Independent boundary probes for staged publication; real owned Neo4j required."""
import os
from uuid import uuid4

import pytest

import lct.neo4j_graph as module
from lct.common import ToolError
from tests.test_neo4j_review_independent import payload


@pytest.fixture
def graph():
    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('owned Neo4j required')
    with module.Neo4jGraph(uri, os.getenv('LCT_TEST_NEO4J_USER', 'neo4j'),
                          os.getenv('LCT_TEST_NEO4J_PASSWORD', 'synthetic-lct-batch1-only'),
                          os.getenv('LCT_TEST_NEO4J_DATABASE', 'neo4j')) as instance:
        yield instance


def test_complete_version_skips_batch_preparation(graph, monkeypatch):
    snapshot = payload()
    ns = 'independent-complete-' + uuid4().hex
    graph.import_snapshot(ns, 'v1', snapshot)
    def forbidden(*args, **kwargs):
        raise AssertionError('complete version must not prepare write batches')
    monkeypatch.setattr(module, '_batches', forbidden)
    assert graph.import_snapshot(ns, 'v1', snapshot)['already_present'] is True


def test_same_count_indexed_field_corruption_cannot_publish(graph, monkeypatch):
    original = module._verify
    ns = 'independent-property-' + uuid4().hex
    def corrupt(session, scope, *args, **kwargs):
        # Leave raw_json and row count unchanged; public filtering uses this separate field.
        session.run('MATCH (n:LCTNode {namespace:$namespace,version:$version,node_id:"a"}) '
                    'SET n.qualname="wrong indexed value"', **scope).consume()
        return original(session, scope, *args, **kwargs)
    monkeypatch.setattr(module, '_verify', corrupt)
    with pytest.raises(ToolError, match='verification'):
        graph.import_snapshot(ns, 'v1', payload())
    with pytest.raises(ToolError, match='missing|incomplete'):
        graph.get_nodes(ns, 'v1', ['a'])
    monkeypatch.setattr(module, '_verify', original)
    graph.import_snapshot(ns, 'v1', payload())
    assert graph.get_nodes(ns, 'v1', ['a'])[0]['qualname'] == 'a'


def test_fenced_owner_cannot_publish_or_release_replacement(graph, monkeypatch):
    original = module._verify
    ns = 'independent-fenced-' + uuid4().hex
    def takeover(session, scope, *args, **kwargs):
        original(session, scope, *args, **kwargs)
        # Simulate a different claimant after validation's transaction has committed.
        session.run('MATCH (s:LCTSnapshot {namespace:$namespace,version:$version}) '
                    'SET s.owner="replacement",s.state="writing",s.lease_until=$lease',
                    **scope, lease=10**12).consume()
    monkeypatch.setattr(module, '_verify', takeover)
    with pytest.raises(ToolError, match='ownership'):
        graph.import_snapshot(ns, 'v1', payload())
    with graph.driver.session(database=graph.database) as session:
        row = session.run('MATCH (s:LCTSnapshot {namespace:$ns,version:"v1"}) '
                          'RETURN s.owner AS owner,s.state AS state,s.complete AS complete', ns=ns).single()
        assert tuple(row.values()) == ('replacement', 'writing', False)
    with pytest.raises(ToolError, match='missing|incomplete'):
        graph.snapshot_info(ns, 'v1')


def test_lost_publish_ack_does_not_unpublish_and_retry_is_idempotent(graph):
    original = graph.driver
    ns = 'independent-lost-ack-' + uuid4().hex
    fired = []
    class Tx:
        def __init__(self, transaction): self.transaction = transaction; self.publishing = False
        def __enter__(self): self.transaction.__enter__(); return self
        def __exit__(self, *args):
            result = self.transaction.__exit__(*args)
            if self.publishing and args[0] is None and not fired:
                fired.append(True)
                raise RuntimeError('simulated lost commit acknowledgement')
            return result
        def run(self, query, **kwargs):
            if 's.complete=true' in query:
                self.publishing = True
            return self.transaction.run(query, **kwargs)
    class Session:
        def __init__(self, session): self.session = session
        def __enter__(self): self.session.__enter__(); return self
        def __exit__(self, *args): return self.session.__exit__(*args)
        def run(self, *args, **kwargs): return self.session.run(*args, **kwargs)
        def begin_transaction(self, **kwargs): return Tx(self.session.begin_transaction(**kwargs))
    class Driver:
        def session(self, **kwargs): return Session(original.session(**kwargs))
    graph.driver = Driver()
    try:
        with pytest.raises(RuntimeError, match='lost commit acknowledgement'):
            graph.import_snapshot(ns, 'v1', payload())
    finally:
        graph.driver = original
    assert fired == [True]
    assert graph.snapshot_info(ns, 'v1')['graph'] == payload()['graph']
    assert graph.import_snapshot(ns, 'v1', payload())['already_present'] is True
    with original.session(database=graph.database) as session:
        assert session.run('MATCH (n:LCTNode {namespace:$ns,version:"v1"}) '
                           'RETURN count(n) AS count', ns=ns).single()['count'] == 2
