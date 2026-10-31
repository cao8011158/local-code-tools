"""Optional value projection is independently bound to immutable code evidence."""

import json
import os
from uuid import uuid4

import pytest

from lct.common import ToolError, digest
from lct.neo4j_graph import (PROJECTION_SCHEMA, VALUE_PROJECTION_SCHEMA, _snapshot_payload,
                             _validate_value, value_relation_query, load_snapshot, Neo4jGraph)
from lct.official_mcp import (read_cypher_requests, value_read_cypher_requests,
                              value_node_read_cypher_requests, raw_fragment_requests)
from lct.publication import _descriptor, _verify
from lct.storage import build
from tests.synthetic_support import initialize


def sample():
    module = dict(node_id='mod', kind='module', repository='r', path='a.py')
    function = dict(node_id='fun', kind='function', repository='r', path='a.py')
    value = dict(nodes=[dict(id='value:container', module='mod', kind='container'),
                        dict(id='value:entry', module='mod', kind='entry',
                             container='value:container', key='go', present=True),
                        dict(id='value:read', module='mod', kind='read', site_id='site')],
                 edges=[dict(source='value:container', target='value:entry', kind='ADDRESSES'),
                        dict(source='value:read', target='value:entry', kind='READS'),
                        dict(source='value:read', target='fun', kind='POSSIBLE_CALLS')],
                 reads=[dict(entry='value:entry', read='value:read',
                             consumer_repository='r', consumer_path='a.py')])
    return [module, function], value


def test_v2_payload_stays_four_key_and_v3_binds_all_value_support():
    nodes, value = sample()
    old = digest(_snapshot_payload(nodes, [], {}, {}))
    assert old == digest(_snapshot_payload(nodes, [], {}, {}, None))
    _validate_value(value, nodes)
    new = digest(_snapshot_payload(nodes, [], {}, {}, value))
    assert new != old
    value['reads'][0]['consumer_path'] = 'changed.py'
    assert digest(_snapshot_payload(nodes, [], {}, {}, value)) != new
    with pytest.raises(ToolError, match='subscription'):
        _validate_value(value, nodes)


def test_native_value_templates_scope_known_ids_and_bound_fragments():
    fp = 'a' * 64
    marker, query = value_read_cypher_requests('ns', 'v', ['value:entry', 'fun'], fp,
                                               direction='both', limit=16)
    assert marker['arguments']['params']['projection_schema'] == VALUE_PROJECTION_SCHEMA
    assert "value_projection:'complete'" in query['arguments']['query']
    assert 'value_id:wanted' in query['arguments']['query']
    assert 'node_id:wanted' in query['arguments']['query']
    assert 'LCTValueEdge' in query['arguments']['query']
    assert query['arguments']['params']['fetch'] == 17
    assert 'LCTValue' in value_node_read_cypher_requests('ns', 'v', ['value:entry'], fp)[1]['arguments']['query']
    assert 'LCTValueEdge' in raw_fragment_requests('ns', 'v', 'edge-id', fp,
        entity='value-edge', projection_schema=VALUE_PROJECTION_SCHEMA)[1]['arguments']['query']
    assert read_cypher_requests('ns', 'v', ['fun'], fp)[0]['arguments']['params']['projection_schema'] == PROJECTION_SCHEMA
    assert read_cypher_requests('ns', 'v', ['fun'], fp,
        projection_schema=VALUE_PROJECTION_SCHEMA)[0]['arguments']['params']['projection_schema'] == VALUE_PROJECTION_SCHEMA
    with pytest.raises(ToolError, match='v3'):
        raw_fragment_requests('ns', 'v', 'edge-id', fp, entity='value-edge')
    with pytest.raises(ToolError, match='16'):
        value_node_read_cypher_requests('ns', 'v', list(map(str, range(17))), fp)
    with pytest.raises(ToolError, match='direction'):
        value_relation_query('sideways')


def test_publication_descriptor_requires_actual_schema_and_value_counts():
    nodes, value = sample()
    snapshot = dict(nodes=nodes, edges=[], fingerprint='b' * 64,
                    projection_schema=VALUE_PROJECTION_SCHEMA, value_flow=value)
    binding = _descriptor('bolt://local', 'neo4j', 'ns', 'v', snapshot)
    assert (binding['value_nodes'], binding['value_edges'], binding['value_reads']) == (3, 3, 1)

    class Graph:
        def snapshot_summary(self, namespace, version):
            return dict(fingerprint=binding['fingerprint'], projection_schema=VALUE_PROJECTION_SCHEMA,
                        nodes=2, edges=0, native_edges=3, value_projection='complete',
                        value_nodes=3, value_edges=3, value_reads=1)

    _verify(Graph(), binding)
    binding['value_reads'] = 0
    with pytest.raises(ToolError, match='differs'):
        _verify(Graph(), binding)


@pytest.fixture
def service():
    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('owned Neo4j required')
    with Neo4jGraph(uri, os.environ['LCT_TEST_NEO4J_USER'],
                    os.environ['LCT_TEST_NEO4J_PASSWORD'],
                    os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
        yield graph


def captured(tmp_path):
    config, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    (repo / 'src/a.py').write_text("def first(): pass\ndef second(): pass\nregistry={'go':first}\nregistry['go']=second\n")
    (repo / 'src/b.py').write_text("from a import registry as imported\nalias=imported\ndef run():\n    alias['go']()\ndef missing():\n    alias['future']()\n")
    built = build(config, offline=True, lexical_only=True)
    return load_snapshot(config, built['version'])


def test_captured_value_projection_native_and_old_scope_conflict(tmp_path, service):
    data = captured(tmp_path)
    assert data['projection_schema'] == VALUE_PROJECTION_SCHEMA
    namespace = 'dev-value-' + uuid4().hex
    service.import_snapshot(namespace, data['version'], data)
    marker = service.snapshot_summary(namespace, data['version'])
    assert marker['value_nodes'] == len(data['value_flow']['nodes'])
    assert marker['value_edges'] == len(data['value_flow']['edges'])
    missing = next(n for n in data['value_flow']['nodes'] if n['kind'] == 'entry' and
                   n['key'] == 'future')
    assert missing['present'] is False
    assert service.get_value_nodes(namespace, data['version'], [missing['id']],
                                   data['fingerprint']) == [missing]
    expected = next(r for r in data['value_flow']['reads'] if r['entry'] == missing['id'])
    edges = service.get_value_relations(namespace, data['version'], [missing['id']],
                                        data['fingerprint'], ['READS'], 'in')['edges']
    assert len(edges) == 1
    assert edges[0]['consumer_path'] == expected['consumer_path']
    with service.driver.session(database=service.database) as session:
        requests = value_read_cypher_requests(namespace, data['version'], [missing['id']],
                                              data['fingerprint'], ['READS'], 'in')
        assert len(list(session.run(requests[1]['arguments']['query'],
                                    **requests[1]['arguments']['params']))) == 1
    old = dict(data)
    old.pop('value_flow')
    old['projection_schema'] = PROJECTION_SCHEMA
    old['fingerprint'] = digest(_snapshot_payload(old['nodes'], old['edges'],
                                                   old['graph'], old['source']))
    with pytest.raises(ToolError, match='different projection'):
        service.import_snapshot(namespace, data['version'], old)


def test_value_batch_failure_hidden_then_retry(tmp_path, service, monkeypatch):
    import lct.neo4j_graph as projection
    data = captured(tmp_path)
    namespace = 'dev-value-retry-' + uuid4().hex
    original = projection._write

    def fail(session, scope, owner, query, rows=None, state='writing'):
        original(session, scope, owner, query, rows, state)
        if 'CREATE (n:LCTValue:' in query:
            raise RuntimeError('after committed value batch')

    monkeypatch.setattr(projection, '_write', fail)
    with pytest.raises(RuntimeError, match='after committed'):
        service.import_snapshot(namespace, data['version'], data)
    with pytest.raises(ToolError, match='incomplete'):
        service.snapshot_summary(namespace, data['version'])
    monkeypatch.setattr(projection, '_write', original)
    service.import_snapshot(namespace, data['version'], data)
    assert service.import_snapshot(namespace, data['version'], data)['already_present']
