"""Template validation independent of the optional Neo4j service."""
import pytest

from lct.common import ToolError
from lct.official_mcp import read_cypher_requests, node_read_cypher_requests, raw_fragment_requests

FP = 'a' * 64


def test_scope_and_template_validation():
    requests = read_cypher_requests("literal-' OR true //", 'v1', ['a', 'a'], FP,
                                    ['CALLS'], 'both', 2)
    assert len(requests) == 2
    marker, relations = (request['arguments'] for request in requests)
    assert marker['params']['namespace'] == "literal-' OR true //"
    assert relations['params']['ids'] == ['a']
    assert relations['params']['fetch'] == 3
    assert 'node_id:wanted' in relations['query']
    assert 'boundary_id:boundary_key' in relations['query']
    assert 'complete:true' in relations['query']
    assert 'projection_schema:$projection_schema' in relations['query']
    assert 'fingerprint:$expected_fingerprint' in relations['query']
    assert 'raw_too_large' in relations['query']
    assert "literal-' OR true //" not in relations['query']
    with pytest.raises(ToolError, match='fingerprint'):
        read_cypher_requests('n', 'v', ['a'], 'bad')
    with pytest.raises(ToolError, match='direction'):
        read_cypher_requests('n', 'v', ['a'], FP, direction='sideways')
    with pytest.raises(ToolError, match='type'):
        read_cypher_requests('n', 'v', ['a'], FP, types=['DELETE'])


def test_node_batch_and_physical_boundary_identity():
    requests = node_read_cypher_requests('n', 'v', ['a', 'missing'], FP)
    assert 'ORDER BY position' in requests[1]['arguments']['query']
    assert 'raw_too_large' in requests[1]['arguments']['query']
    with pytest.raises(ToolError, match='16 IDs'):
        node_read_cypher_requests('n', 'v', [str(i) for i in range(17)], FP)
    with pytest.raises(ToolError, match='physical boundary'):
        node_read_cypher_requests('n', 'v', ['pkg'], FP, boundary=True)
    assert 'LCTBoundary' in node_read_cypher_requests(
        'n', 'v', ['external:external:pkg'], FP, boundary=True)[1]['arguments']['query']


def test_oversized_raw_fragment_template():
    marker, request = raw_fragment_requests('n', 'v', 'edge-1', FP, offset=8192)
    assert 'complete:true' in request['arguments']['query']
    assert 'LCTEdge' in request['arguments']['query']
    assert 'substring(record.raw_json,$offset,8192)' in request['arguments']['query']
    assert request['arguments']['params']['offset'] == 8192
    with pytest.raises(ToolError, match='offset'):
        raw_fragment_requests('n', 'v', 'edge-1', FP, offset=-1)
