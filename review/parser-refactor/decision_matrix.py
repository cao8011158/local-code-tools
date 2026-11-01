import collections,json,pathlib,time
import pytest
from unittest.mock import patch
from lct.graph import Graph
from lct.common import program_hash
real=Graph.build
rows=[]
def watch(g,*args,**kwargs):
 result=real(g,*args,**kwargs)
 if isinstance(result,tuple) and len(result)==2:
  for s in result[1].get('sites',[]):
   d=s.get('resolution_decision',{})
   rows.append(dict(path=g.nodes[s['execution_owner']]['path'],owner=g.nodes[s['execution_owner']]['qualname'],expression=s['expression'],kind=s['kind'],jedi=d.get('jedi_targets'),custom=d.get('lct_targets'),selected=d.get('selected_targets'),reason=d.get('reason'),rules=d.get('semantic_rules'),unknown=s.get('unresolved_reasons'),complete=s.get('complete'),raw=[e.get('raw') for e in s.get('evidence',[]) if e.get('tool')=='jedi']))
 return result
with patch.object(Graph,'build',watch):
 code=pytest.main(['-q','tests/test_python_pipeline.py','tests/test_python_call_access.py','tests/test_python_review_round3.py','tests/test_python_review_round4.py','tests/test_python_review_regressions.py','tests/test_python_effect_coverage.py','tests/test_core.py','--tb=short'])
counts=collections.Counter((bool(r['jedi']),bool(r['custom']),r['reason']) for r in rows)
output=dict(program_hash=program_hash(),exit_code=code,sites=len(rows),groups=[dict(jedi=k[0],custom=k[1],reason=k[2],count=v) for k,v in counts.items()],rows=rows)
pathlib.Path('review/parser-refactor/decision-matrix.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print('MATRIX',json.dumps(dict(exit_code=code,sites=len(rows),groups=output['groups'])))
raise SystemExit(code)
