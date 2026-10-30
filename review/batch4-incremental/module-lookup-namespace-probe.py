import tempfile,sqlite3,json
from pathlib import Path
from tests.synthetic_support import initialize
from lct.storage import build,manifest,FileDependencies
root=Path(tempfile.mkdtemp(prefix='lct-dep-probe-'))
c,repo=initialize(root/'case')
(repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
(repo/'src/pkg').mkdir()
(repo/'src/caller.py').write_text('from pkg import foo\ndef run():\n    return foo()\n')
b=build(c,offline=True,lexical_only=True)
f,m=manifest(c,b['version'])
with FileDependencies(f,m) as d:
 print('OLD_ADJ',d.adjacent(c['repositories'][0]['name'],'src/caller.py'))
 print('OLD_IMPORTERS_pkgfoo',d.importers(c['repositories'][0]['name'],'pkg.foo'))
 print('OLD_REQUESTERS_pkgfoo',d.requesters(c['repositories'][0]['name'],'pkg.foo'))
 with sqlite3.connect(f/'graph-sites.sqlite') as db:
  print('OLD_REQUESTS',list(db.execute('select source_path,requested_module,lookup_repository from import_requests')))
  print('OLD_SITES',*[json.loads(x[0]) for x in db.execute('select data from sites')],sep='\n')
(repo/'src/pkg/foo.py').write_text('def foo():\n    return 1\n')
u=build(c,offline=True,lexical_only=True)
f,m=manifest(c,u['version'])
print('UPDATE_SCOPE',u['incremental']['analysis_scope'])
with sqlite3.connect(f/'graph-sites.sqlite') as db:
 print('NEW_SITES',*[json.loads(x[0]) for x in db.execute('select data from sites') if 'caller.py' in x[0]],sep='\n')
 print('NEW_REQUESTS',list(db.execute('select source_path,requested_module,lookup_repository from import_requests')))
print('ROOT',root)
