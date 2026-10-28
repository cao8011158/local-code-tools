import json, sys, tempfile, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer

case = sys.argv[2]
n = int(sys.argv[3])
base = '''
def alpha(x):
    return x()
def beta(x):
    return x()
def target():
    pass
def other():
    pass
alias = target
def dispatch(v):
    return alpha(v)
def invoke():
    alpha(target)
    beta(alias)
    dispatch(other)
    alias()
    target()
    choice = target if True else other
    choice()
'''
registry = '''
REG = {}
def register(key, handler):
    REG[key] = handler
def f(): pass
def g(): pass
register("f", f)
register("g", g)
def call():
    fn = REG["f"]
    fn()
'''
bound = '''
class Worker:
    def __init__(self, cb):
        self.cb = cb
    def act(self, x):
        return self.cb(x)
def first(): pass
def second(): pass
def call():
    w = Worker(first)
    w.act(second)
    alias = w.act
    alias(first)
'''
reentry = '''
def rec(f):
    if f:
        return rec(f)
    return f()
def end(): pass
def call():
    rec(end)
'''
uncertain = '''
def target(x):
    return x()
def a(): pass
def b(): pass
def call(dyn):
    cb = a if dyn else b
    target(cb)
    unknown_object.handler(a)
    unknown_object(a)
'''
sources = {'base':base, 'registry':registry, 'bound':bound, 'reentry':reentry, 'uncertain':uncertain}
text = sources[case] + ''.join(f'\ndef unrelated_{i}(x):\n    pass\ndef do_{i}():\n    unrelated_{i}(None)\n' for i in range(n))
with tempfile.TemporaryDirectory() as tmp:
    nodes, trees = python_nodes(dict(repository='fixture',path='src/sample.py',text=text,is_test=False,sha256=digest(text)))
    g = Graph(nodes, trees, [dict(name='fixture',path=tmp,head='test',closed_world=True)])
    counts = Counter(); keys = set()
    query = Analyzer.query
    may = Analyzer.may_call
    candidate = Analyzer.candidate_sites if hasattr(Analyzer, 'candidate_sites') else None
    def counting_query(self,scope,expr,goto=False):
        counts['query_calls'] += 1
        key=(self.module_for[scope],expr.end_lineno,expr.end_col_offset,goto)
        keys.add(key)
        if key not in self.queries: counts['query_misses'] += 1
        return query(self,scope,expr,goto)
    def counting_may(self,function,site):
        counts['may_call'] += 1
        return may(self,function,site)
    Analyzer.query=counting_query
    Analyzer.may_call=counting_may
    if candidate:
        def counting_candidate(self,function):
            counts['candidate_requests'] += 1
            result = candidate(self,function)
            for site in result:
                counts['candidate_visits'] += 1
                yield site
        Analyzer.candidate_sites=counting_candidate
    start=time.monotonic()
    edges, info=g.build()
    elapsed=time.monotonic()-start
    byid={x['node_id']:x['qualname'] for x in nodes}
    def normalize_site(s):
        return dict(expression=s['expression'],owner=byid[s['execution_owner']],line=s['line'],targets=sorted(byid.get(t,t) for t in s['targets']),unknown=s['unknown_origin'],complete=s['complete'],reasons=s['unresolved_reasons'],basis=s['completeness_basis'],resolution=s['resolution_kind'],decision=s['resolution_decision'],boundaries=s['boundaries'])
    def normalize_edge(e):
        return {k:(byid.get(v,v) if k in ('source','target') else v) for k,v in e.items() if k not in ('edge_id','source_version_id','target_version_id','site_id')}
    payload=dict(case=case,n=n,elapsed=round(elapsed,3),counts=dict(counts),unique_keys=len(keys),sites=[normalize_site(s) for s in info['sites']],edges=[normalize_edge(e) for e in edges])
    print(json.dumps(payload,sort_keys=True))
