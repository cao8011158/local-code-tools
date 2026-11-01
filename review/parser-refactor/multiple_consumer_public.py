import json,sqlite3,tempfile
from pathlib import Path
from lct.storage import build,manifest
from tests.synthetic_support import initialize,forbid_provider
with tempfile.TemporaryDirectory() as td:
 c,repo=initialize(Path(td)/'case');(repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink();c['retained_versions']=8
 path=repo/'src/demo.py';versions=[];old=None
 def sites(v):
  folder,_=manifest(c,v)
  with sqlite3.connect(folder/'graph-sites.sqlite') as db:
   return sorted([json.loads(x) for (x,) in db.execute('select data from sites') if json.loads(x)['expression']=='alias'],key=lambda x:x['line'])
 for target in ('first','second',None,'first'):
  binding=f'alias={target}\n' if target else '# alias absent\n'
  path.write_text('def first():pass\ndef second():pass\n'+binding+'def run():alias()\ndef other():alias()\n')
  with forbid_provider():r=build(c,offline=True,lexical_only=True)
  ss=sites(r['version']);assert len(ss)==2
  for s in ss:
   assert (len(s['targets'])==1 and f':function:{target}#' in s['targets'][0]) if target else not s['targets']
  if versions:assert r['incremental']['analysis_scope']['mode']=='incremental-owners'
  else:old=ss
  versions.append(r['version']);assert sites(versions[0])==old
  print(json.dumps(dict(target=target,mode=r['incremental']['analysis_scope']['mode'],consumers=len(ss),old_unchanged=True)))
