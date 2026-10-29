"""Profile actual scoped lookup plans, independently of response byte counters."""
import json, os, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from lct.neo4j_graph import Neo4jGraph, REL_TYPES
report=json.loads((ROOT/'review/query-locality-repair/real-neo4j.json').read_text())
db=sqlite3.connect('/tmp/lct-query-repair-restored/data/versions/20261029T122833-1278b3bc4b/catalog.sqlite')
source=db.execute("select source from edges where kind='CALLS' limit 1").fetchone()[0];db.close()
queries=[]
for row in report['reads']:
 q=row['query']
 if ('RETURN e.edge_id' in q or 'n.node_id IN $ids' in q) and q not in queries:queries.append(q)
results=[]
with Neo4jGraph(*[os.environ['LCT_TEST_NEO4J_'+k] for k in ('URI','USER','PASSWORD','DATABASE')]) as graph:
 with graph.driver.session(database=graph.database) as session:
  for query in queries:
   p=dict(namespace=report['namespace'],version=report['neo4j_version'],ids=[source],types=['CALLS'],direction='out',cursor=None,fetch=17,allowed=sorted(REL_TYPES))
   result=session.run('PROFILE '+query,**p);rows=list(result);summary=result.consume()
   results.append(dict(query=query,rows=len(rows),plan=summary.profile))
(ROOT/'review/query-locality-repair/query-plans.json').write_text(json.dumps(results,indent=2))
def nodes(plan):
 yield plan
 for child in plan.get('children',[]):yield from nodes(child)
for r in results:
 print(json.dumps(dict(rows=r['rows'],operators=[(x.get('operatorType'),x.get('rows'),x.get('dbHits')) for x in nodes(r['plan'])])))
