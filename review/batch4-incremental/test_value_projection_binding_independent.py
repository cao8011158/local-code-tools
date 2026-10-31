"""Supplement: actual v3 publication binding and function-to-value reverse lookup."""
import json
import os
import uuid

import pytest

from lct.neo4j_graph import Neo4jGraph, load_snapshot
from lct.official_mcp import value_read_cypher_requests
from lct.publication import bind_current, resolve_current
from lct.storage import build
from tests.synthetic_support import initialize


@pytest.mark.skipif(not os.getenv('LCT_TEST_NEO4J_URI'), reason='owned Neo4j required')
def test_real_publication_binding_and_function_reverse_lookup(tmp_path):
    config, repo = initialize(tmp_path / 'binding')
    (repo/'src/weights.py').unlink()
    (repo/'docs/guide.md').unlink()
    (repo/'src/provider.py').write_text("def handler(): pass\nregistry={'go':handler}\n")
    (repo/'src/consumer.py').write_text("from provider import registry\ndef run(): registry['go']()\n")
    built=build(config,offline=True,lexical_only=True)
    snapshot=load_snapshot(config,built['version'])
    ns='root-value-binding-'+uuid.uuid4().hex
    uri,user,password,database=(os.environ[k] for k in ('LCT_TEST_NEO4J_URI',
        'LCT_TEST_NEO4J_USER','LCT_TEST_NEO4J_PASSWORD','LCT_TEST_NEO4J_DATABASE'))
    binding=bind_current(config,ns,database,uri=uri,user=user,password=password)
    assert binding['projection_schema']=='native-value-v3'
    assert binding['value_reads']==1
    assert resolve_current(config,uri=uri,user=user,password=password)==binding
    target=next(n['node_id'] for n in snapshot['nodes'] if n.get('qualname')=='handler')
    expected={tuple(e[k] for k in ('source','kind','target')) for e in snapshot['value_flow']['edges']
              if e['target']==target}
    assert {e[1] for e in expected}=={'VALUE','POSSIBLE_CALLS'}
    requests=value_read_cypher_requests(ns,built['version'],[target],binding['fingerprint'],
        types=['VALUE','POSSIBLE_CALLS'],direction='in',limit=1)
    actual=set()
    with Neo4jGraph(uri,user,password,database) as graph:
        with graph.driver.session(database=database) as session:
            while True:
                args=requests[1]['arguments'];page=list(session.run(args['query'],**args['params']))
                if not page:break
                row=json.loads(page[0]['raw']);actual.add(tuple(row[k] for k in ('source','kind','target')))
                if len(page)==1:break
                requests=value_read_cypher_requests(ns,built['version'],[target],binding['fingerprint'],
                    types=['VALUE','POSSIBLE_CALLS'],direction='in',limit=1,cursor=page[0]['id'])
    assert actual==expected


@pytest.mark.skipif(not os.getenv('LCT_TEST_NEO4J_URI'), reason='owned Neo4j required')
def test_oversized_value_row_requires_lossless_fragments(tmp_path):
    from lct.common import ToolError, canonical
    from lct.official_mcp import value_node_read_cypher_requests,raw_fragment_requests
    config,repo=initialize(tmp_path/'oversized')
    (repo/'src/weights.py').unlink()
    (repo/'docs/guide.md').unlink()
    key='x'*70000
    (repo/'src/producer.py').write_text('def target(): pass\nregistry={'+repr(key)+':target}\n')
    (repo/'src/consumer.py').write_text('from producer import registry\ndef run(): registry['+repr(key)+']()\n')
    built=build(config,offline=True,lexical_only=True)
    snapshot=load_snapshot(config,built['version'])
    entry=next(n for n in snapshot['value_flow']['nodes'] if n['kind']=='entry')
    ns='root-value-large-'+uuid.uuid4().hex
    args=[os.environ[k] for k in ('LCT_TEST_NEO4J_URI','LCT_TEST_NEO4J_USER',
                                 'LCT_TEST_NEO4J_PASSWORD','LCT_TEST_NEO4J_DATABASE')]
    with Neo4jGraph(*args) as graph:
        graph.import_snapshot(ns,built['version'],snapshot)
        with pytest.raises(ToolError,match='fragment'):
            graph.get_value_nodes(ns,built['version'],[entry['id']],snapshot['fingerprint'])
        with graph.driver.session(database=graph.database) as session:
            req=value_node_read_cypher_requests(ns,built['version'],[entry['id']],snapshot['fingerprint'])[1]['arguments']
            row=session.run(req['query'],**req['params']).single()
            assert row['raw'] is None and row['raw_too_large'] is True
            fragments=[];offset=0
            while True:
                req=raw_fragment_requests(ns,built['version'],entry['id'],snapshot['fingerprint'],
                    entity='value-node',offset=offset,projection_schema='native-value-v3')[1]['arguments']
                row=session.run(req['query'],**req['params']).single()
                assert 0<len(row['fragment'])<=8192
                fragments.append(row['fragment']);offset+=len(row['fragment'])
                if offset==row['length']:break
            assert ''.join(fragments)==canonical(entry)
