"""Independent Batch 1 review probes; real service, no embedding calls."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from lct.common import ToolError, canonical, digest
from lct.neo4j_graph import Neo4jGraph


def payload():
    nodes = [dict(node_id=x, kind='function', repository='r', qualname=x) for x in ('a', 'b')]
    pairs = [('a', 'b'), ('a', 'external:pkg'), ('external:pkg', 'a'), ('a', None), ('a', 'a')]
    edges = [dict(edge_id=str(i), kind='CALLS', source=s, target=t,
                  unknown_origin=i != 0, complete=i == 0, site_id='site-'+str(i))
             for i, (s, t) in enumerate(pairs)]
    p = dict(version='v1', nodes=nodes, edges=edges, graph={'sites': [{'reason': 'unknown callback'}]},
             source={'repositories': [{'name': 'r', 'git_head': 'fixture-head'}]})
    return seal(p)


def seal(p):
    p['fingerprint'] = digest(canonical({k: p[k] for k in ('nodes', 'edges', 'graph', 'source')}))
    return p


@pytest.fixture
def graph():
    if not os.environ.get('LCT_TEST_NEO4J_URI'):
        pytest.skip('owned Neo4j URI required')
    with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'], os.environ['LCT_TEST_NEO4J_USER'],
                    os.environ['LCT_TEST_NEO4J_PASSWORD'], os.environ['LCT_TEST_NEO4J_DATABASE']) as g:
        yield g


def test_external_mixed_limits_native_and_literal_scope(graph):
    p = payload(); ns = "review-' OR true //-" + uuid.uuid4().hex
    graph.import_snapshot(ns, 'v1', p)
    for direction in ('in', 'out', 'both'):
        expected = [e for e in p['edges'] if (e['source']=='a' if direction=='out' else
                    e['target']=='a' if direction=='in' else 'a' in (e['source'], e['target']))]
        for limit in (1, 2, 5):
            assert graph.get_relations(ns, 'v1', ['a'], direction=direction, limit=limit) == {
                'edges': expected[:limit], 'has_more': len(expected)>limit,
                'next_cursor': expected[limit-1]['edge_id'] if len(expected)>limit else None}
    assert graph.get_relations(ns, 'v1', ['external:pkg'])['edges'] == p['edges'][1:3]
    assert graph.get_relations(ns, 'v1', ['a'], types=[])['edges'] == []
    assert graph.get_nodes(ns, 'v1', ['b', 'missing', 'a', 'b']) == list(reversed(p['nodes']))
    with graph.driver.session(database=graph.database) as s:
        row = s.run('MATCH (n:LCTNode {namespace:$ns,version:"v1"}) '
                    'OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n) AS n, count(r) AS r', ns=ns).single()
        # V2 projects every logical edge; four originate at code node a.
        assert (row['n'], row['r']) == (2, 4)
    with pytest.raises(ToolError):
        graph.snapshot_info(ns+'missing', 'v1')


def test_concurrent_same_snapshot_and_conflicting_content(graph):
    p = payload(); ns='review-concurrent-'+uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:graph.import_snapshot(ns,'v1',p),range(2)))
    assert sorted(r['already_present'] for r in results)==[False, True]
    assert graph.get_relations(ns,'v1',['a'])['edges']==p['edges']
    changed=deepcopy(p); changed['nodes'][0]['qualname']='changed'; seal(changed)
    with pytest.raises(ToolError,match='different content'):
        graph.import_snapshot(ns,'v1',changed)
    assert graph.get_nodes(ns,'v1',['a'])[0]['qualname']=='a'


def test_bad_input_never_publishes(graph):
    p=payload(); ns='review-invalid-'+uuid.uuid4().hex
    p['nodes'].append(p['nodes'][0]); seal(p)
    with pytest.raises(ToolError,match='Duplicate'):
        graph.import_snapshot(ns,'v1',p)
    with pytest.raises(ToolError,match='missing'):
        graph.snapshot_info(ns,'v1')
