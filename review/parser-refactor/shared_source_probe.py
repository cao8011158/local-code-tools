import collections,json,tempfile
from pathlib import Path
from unittest.mock import patch
from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze
source='def first():pass\na0=first\n'+''.join(f'a{i}=a{i-1}\n' for i in range(1,12))+'def run():\n'+''.join(' a11()\n' for _ in range(20))
counts=collections.Counter();real=Analyzer.reaching
def watch(a,scope,name,before):
 if a.nodes[scope]['kind']=='module':counts[(name,str(before))]+=1
 return real(a,scope,name,before)
with tempfile.TemporaryDirectory() as p,patch.object(Analyzer,'reaching',watch):
 r=analyze(Path(p),{'src/demo.py':source},closed=False)
 print(json.dumps(dict(module_source_lookups=sum(counts.values()),max_repeated_same_lookup=max(counts.values()),sites=len(r[2]['sites']),tool_first=r[2].get('tool_first_sites'),sample=list(counts.most_common(3)))))
