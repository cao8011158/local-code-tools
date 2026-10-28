import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
from lct.common import digest
from lct.extract import python_nodes
from lct.python_analysis import Analyzer
manifest=json.loads(Path(sys.argv[3]).read_text())
repos={r['name']:r for r in manifest['repositories']}
nodes={};trees={}; t=time.monotonic()
for f in manifest['files']:
 if not f['path'].endswith('.py'):continue
 source=(Path(repos[f['repository']]['path'])/f['path']).read_text(encoding='utf-8-sig')
 ns,ts=python_nodes(dict(repository=f['repository'],path=f['path'],text=source,is_test=f['is_test'],sha256=digest(source),snapshot_id=f.get('snapshot_id','probe')))
 nodes.update({n['node_id']:n for n in ns});trees.update(ts)
print('extracted',len(nodes),len(trees),round(time.monotonic()-t,2),file=sys.stderr,flush=True)
a=Analyzer(nodes,trees,repos,lambda repo,name:set())
try:
 print('initialized',len(a.sites),round(time.monotonic()-t,2),file=sys.stderr,flush=True)
 records=[]
 print('pre_queries',len(a.queries),round(time.monotonic()-t,2),file=sys.stderr,flush=True)
 sites=[s for s in a.sites if nodes[a.module_for[s['execution_owner']]]['path']=='packages/dnd5e-engine/src/dnd5e_engine/activities/scale.py']
 if sys.argv[2]=='prime':
  for s in sites:
   a.query(s['execution_owner'],s['_expr'])
 for s in sites:
  if s['line'] in (80,82,146,152,155) and s['expression']=='config.get':
   expr=s['_expr'];owner=s['execution_owner'];k0=(a.module_for[owner],expr.end_lineno,expr.end_col_offset,False);pre=a.queries.get(k0);r=a.query(owner,expr)
   key=(a.module_for[owner],expr.end_lineno,expr.end_col_offset,False)
   records.append(dict(line=s['line'],pre_cached=pre is not None,atoms=[(x.kind,x.target) for x in r.atoms],reasons=sorted(r.reasons),raw=a.queries[key][1]))
 print(json.dumps(dict(seconds=round(time.monotonic()-t,2),sites=len(a.sites),records=records),sort_keys=True))
finally:a.close()
