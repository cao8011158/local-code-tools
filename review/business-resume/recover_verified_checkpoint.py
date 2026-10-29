"""Recover validated published artifacts, preserving the rejected workspace intact.

This explicitly constructs a schema-2 recovery transport; it is not a successful
backup of the rejected source directory. Production restore verifies it and
rebinds into unsynchronized storage; then production backup runs there normally.
"""
import hashlib,json,sqlite3,sys,zipfile,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from lct.common import canonical,config,program_hash,identity,SCHEMA,FORMAT
from lct.management import restore
base=Path('/workspace/scratch/413372d9a5a5');c=config(base/'batch3-restored-config.json');data=Path(c['data'])
version=json.loads((data/'current.json').read_text())['version'];folder=data/'versions'/version;m=json.loads((folder/'manifest.json').read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
assert m['program_hash']==program_hash() and m['config_hash']==identity(c) and m['state']=='complete'
for name,digest in m['artifacts'].items():
 assert sha(folder/name)==digest and (folder/name).stat().st_size==m['artifact_sizes'][name]
with sqlite3.connect((folder/'catalog.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert db.execute('select count(*) from nodes').fetchone()[0]==m['node_count']
 assert db.execute('select count(*) from edges').fetchone()[0]==sum(m['edges'].values())
entries={p.relative_to(ROOT).as_posix():p for p in (ROOT/'lct').glob('*.py')}
for name in ('uv.lock','pyproject.toml','local_code_tools.py','register_mcp.py','README.md'):
 entries[name]=ROOT/name
for name in list(m['artifacts'])+['manifest.json','build-state.json']:
 entries['data/versions/'+version+'/'+name]=folder/name
for name in ('current.json','freshness.json','ledger.json','cursor-key.json','vectors.sqlite'):
 if (data/name).is_file():entries['data/'+name]=data/name
cache_target=Path('/tmp/lct-b3-cache-consistent-20261029.sqlite')
assert not cache_target.exists()
if (data/'vectors.sqlite').exists():
 with tempfile.TemporaryDirectory(prefix='lct-cache-freeze-',dir='/tmp') as temp:
  frozen=Path(temp)
  names=[n for n in ('vectors.sqlite','vectors.sqlite-wal','vectors.sqlite-shm') if (data/n).exists()]
  before={n:sha(data/n) for n in names}
  for n in names:shutil.copyfile(data/n,frozen/n)
  assert before=={n:sha(data/n) for n in names}
  assert before=={n:sha(frozen/n) for n in names}
  src=sqlite3.connect((frozen/'vectors.sqlite').as_uri()+'?mode=ro',uri=True)
  dst=sqlite3.connect(cache_target)
  try:
   assert src.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   src.backup(dst)
   assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   assert src.execute('select count(*) from vectors').fetchone()==dst.execute('select count(*) from vectors').fetchone()
  finally:src.close();dst.close()
 entries['data/vectors.sqlite']=cache_target
normalized={k:v for k,v in c.items() if not k.startswith('_')};encoded=canonical(normalized).encode()
checks={name:sha(p) for name,p in entries.items()};checks['config.json']=hashlib.sha256(encoded).hexdigest()
archive=Path('/tmp/lct-b3-verified-recovery-v2-20261029.zip');target=Path('/tmp/lct-b3-isolated-v2-20261029')
assert not target.exists()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=2) as z:
 for name,p in entries.items():z.write(p,name)
 z.writestr('config.json',encoded)
 z.writestr('backup-manifest.json',canonical(dict(schema=2,version=version,config_hash=identity(c),program_hash=program_hash(),index_schema=SCHEMA,index_format=FORMAT,files=checks,excluded=['sidecar and synchronization remnants preserved in original snapshot; recovery from manifest-verified artifacts'])))
result=restore(c,archive,target)
r=dict(result=result,bootstrap_transport_sha256=sha(archive),bootstrap_transport_bytes=archive.stat().st_size,original_catalog_sha256=m['artifacts']['catalog.sqlite'],original_untouched=True,original_sidecar_still_present=(folder/'catalog.sqlite-journal').is_file(),recovery_not_product_source_backup=True)
(ROOT/'review/business-resume/isolated-recovery.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
