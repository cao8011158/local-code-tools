import tempfile,sqlite3,json
from pathlib import Path
from tests.synthetic_support import initialize
from lct.storage import build,manifest,FileDependencies
root=Path(tempfile.mkdtemp(prefix='lct-effect-probe-'))
c,repo=initialize(root/'case');(repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
(repo/'src/b.py').write_text('def target():\n    pass\nregistry={"go": target}\ndef run():\n    return registry["go"]()\n')
(repo/'src/a.py').write_text('def noise():\n    pass\n')
old=build(c,offline=True,lexical_only=True)
folder,m=manifest(c,old['version'])
with FileDependencies(folder,m) as d:
 print('ADJ_A',d.adjacent('synthetic-review','src/a.py'),'ADJ_B',d.adjacent('synthetic-review','src/b.py'))
 print('REQUESTS',list(d.db.execute('select source_path,requested_module from import_requests')))
def sites(version):
 folder,_=manifest(c,version)
 with sqlite3.connect(folder/'graph-sites.sqlite') as db:return [json.loads(raw) for (raw,) in db.execute('select data from sites') if 'src/b.py' in raw]
a=sites(old['version']);print('OLD',[(x['targets'],x['complete'],x['unresolved_reasons'],x['resolution_decision']['write_source_coverage']) for x in a])
(repo/'src/a.py').write_text('def noise():\n    a_slot = {}\n    a_slot["x"] = 1\n')
new=build(c,offline=True,lexical_only=True);b=sites(new['version'])
print('NEW',[(x['targets'],x['complete'],x['unresolved_reasons'],x['resolution_decision']['write_source_coverage']) for x in b])
print('EQUAL',a==b,'ROOT',root)
