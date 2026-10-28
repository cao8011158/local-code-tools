"""Bounded offline baseline graph / candidate build comparison; no embedding requests."""
import collections
import gzip
import hashlib
import json
import resource
import sys
import threading
import time
from pathlib import Path

code, mode, output, data, config_path = sys.argv[1:]
sys.path.insert(0, code)
from lct.common import config, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer

root = Path('/workspace/scratch/413372d9a5a5')
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
counts = collections.Counter()
original_query = Analyzer.query
original_adjudicate = Analyzer.adjudicate
original_gate = Analyzer.may_call
original_graph = Graph.build

def query(self, scope, expr, goto=False):
    key = (self.module_for[scope], expr.end_lineno, expr.end_col_offset, goto)
    counts['query_calls'] += 1
    counts['hits' if key in self.queries else 'misses'] += 1
    return original_query(self, scope, expr, goto)

def adjudicate(self, *args, **kwargs):
    value = original_adjudicate(self, *args, **kwargs)
    counts['adjudicated_sites'] += 1
    return value

def gate(self, *args, **kwargs):
    counts['may_call_checks'] += 1
    return original_gate(self, *args, **kwargs)

def snapshot(label):
    return dict(label=label, seconds=round(time.monotonic()-started, 3),
                counts=dict(counts), peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def graph(self):
    value = original_graph(self)
    edges, info = value
    # Compare public semantic fields, excluding diagnostic Jedi paths and traces
    # whose private temporary roots differ between isolated processes.
    sites = [{k:v for k,v in s.items() if k != 'evidence'} for s in info['sites']]
    semantic = dict(edges=sorted(edges, key=lambda e:e['edge_id']),
                    sites=sites, metadata={k:v for k,v in info.items() if k != 'sites'})
    payload = json.dumps(semantic, sort_keys=True, separators=(',', ':')).encode()
    with gzip.open(out/'semantics.json.gz', 'wb') as stream:
        stream.write(payload)
    result = snapshot('graph-complete') | dict(semantic_sha256=hashlib.sha256(payload).hexdigest(),
                 edge_count=len(edges), site_count=len(sites), analysis_limited=info['analysis_limited'])
    (out/'graph-result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return value

Analyzer.query, Analyzer.adjudicate, Analyzer.may_call = query, adjudicate, gate
Graph.build = graph

def pulse():
    while True:
        time.sleep(30)
        print(json.dumps(snapshot('progress')), flush=True)

threading.Thread(target=pulse, daemon=True).start()
c = config(config_path)
c['data'] = data
print(json.dumps(snapshot('started')), flush=True)
if mode == 'graph':
    files, repos, fingerprint = inventory(c)
    nodes, asts = extract(files)
    Graph(nodes, asts, repos).build()
elif mode == 'build':
    from lct.storage import build
    m = build(c, offline=True, lexical_only=True)
    result = snapshot('published') | dict(version=m['version'], node_count=m['node_count'],
        edges=m['edges'], call_resolution=m['call_resolution'], artifacts=m['artifacts'],
        dense_ready=m['dense_ready'], embedding_run=m['embedding_run'],
        source_fingerprint=m['source_fingerprint'], program_hash=m['program_hash'])
    (out/'build-result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
else:
    raise ValueError(mode)
