"""Actual Neo4j profile of official read templates, with unrelated graph growth."""
import json
import os
import uuid
from lct.common import canonical,digest
from lct.neo4j_graph import Neo4jGraph
from lct.official_mcp import read_cypher_requests
from tests.test_import_lookup_dependency import build,lookup_edges
from tests.test_core import file

def test_profile_lookup_adjacency():
    nodes,edges=build([file('from a import missing\n','src/b.py'),file('pass\n','src/a.py')])
    imports,lookups=lookup_edges(edges)
    module=lookups[0]['target']; boundary=imports[0]['target']; report=[]
    with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'],os.environ['LCT_TEST_NEO4J_USER'],os.environ['LCT_TEST_NEO4J_PASSWORD'],os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
        for count in (0,2000):
            ns='lookup-profile-'+uuid.uuid4().hex
            extra_nodes=[dict(node_id=f'noise-{i}',kind='function',repository='noise') for i in range(count+1)] if count else []
            extra_edges=[dict(edge_id='noise-edge-'+str(i),source=f'noise-{i}',target=f'noise-{i+1}',kind='CALLS',status='resolved') for i in range(count)]
            snap=dict(version='v1',nodes=nodes+extra_nodes,edges=edges+extra_edges,graph={'sites':[]},source={'repositories':[]})
            snap['fingerprint']=digest(canonical({k:snap[k] for k in ('nodes','edges','graph','source')}))
            graph.import_snapshot(ns,'v1',snap)
            profiles=[]
            for nid,kind in ((module,'LOOKUP_IN'),(boundary,'IMPORTS')):
                req=read_cypher_requests(ns,'v1',[nid],snap['fingerprint'],types=[kind],direction='in')[1]['arguments']
                with graph.driver.session(database=graph.database) as session:
                    result=session.run('PROFILE '+req['query'],**req['params']); rows=list(result); summary=result.consume()
                    ops=[]
                    def walk(plan):
                        ops.append({'operator':plan['operatorType'],'rows':plan.get('rows',0),'db_hits':plan.get('dbHits',0)})
                        for child in plan.get('children',[]):walk(child)
                    walk(summary.profile)
                    assert len(rows)==1
                    assert any('IndexSeek' in x['operator'] for x in ops),ops
                    assert not any('AllNodesScan' in x['operator'] or 'NodeByLabelScan' in x['operator'] for x in ops),ops
                    profiles.append({'kind':kind,'rows':len(rows),'db_hits':sum(x['db_hits'] for x in ops),'operators':ops})
            report.append({'unrelated_edges':count,'queries':profiles})
        assert [q['db_hits'] for q in report[1]['queries']]==[q['db_hits'] for q in report[0]['queries']],report
    print(json.dumps(report,indent=2))
