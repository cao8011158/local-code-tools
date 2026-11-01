"""Bounded static-build profile; diagnostic timeout is not acceptance."""
import cProfile,json,pathlib,pstats,signal,time
from unittest.mock import patch
from lct.common import program_hash
from lct.storage import build
from lct.python_analysis import Analyzer
from tests.synthetic_support import forbid_provider
class DiagnosticStop(BaseException): pass
p=pathlib.Path('/workspace/scratch/45363df3617b')
c=json.loads((p/'task-evidence/jd1-full83-run/acceptance-config.json').read_text())
c['data']=str(p/'task-evidence/parser-refactor-baseline-profile')
active=[];original=Analyzer.__init__
def init(a,*args,**kwargs):
 r=original(a,*args,**kwargs);active.append(a);return r
def stop(*_):raise DiagnosticStop()
profile=cProfile.Profile();started=time.monotonic();status='completed';version=None
signal.signal(signal.SIGALRM,stop);signal.alarm(90)
try:
 with forbid_provider(),patch.object(Analyzer,'__init__',init):
  profile.enable();r=build(c,offline=True,lexical_only=True);version=r['version']
except DiagnosticStop:status='bounded-profile-stopped'
finally:
 signal.alarm(0);profile.disable()
 s=pstats.Stats(profile)
 rows=[dict(file=k[0],line=k[1],function=k[2],primitive=v[0],calls=v[1],self_seconds=v[2],cumulative_seconds=v[3]) for k,v in s.stats.items()]
 counters={}
 if active:
  a=active[-1]
  counters=dict(prepared=a.site_queries_prepared,jedi_queries=a.executed_queries,query_entries=a.query_entries,slot_scope_checks=a.slot_scope_candidates_checked,slot_events=a.slot_events_checked,budget=a.budget,limited=a.limited,preparing=a._preparing_sites)
 output=dict(status=status,version=version,seconds=time.monotonic()-started,program_hash=program_hash(),counters=counters,self_top=sorted(rows,key=lambda x:x['self_seconds'],reverse=True)[:40],cumulative_top=sorted(rows,key=lambda x:x['cumulative_seconds'],reverse=True)[:40],note='cProfile overhead changes timing; cumulative rows overlap, do not sum. Diagnostic partial build, not accepted full graph.')
 (p/'local-only-work/review/parser-refactor/baseline-full83-profile.json').write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps({k:output[k] for k in ['status','seconds','program_hash','counters']}))
