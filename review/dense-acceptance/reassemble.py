"""Join downloaded raw parts and verify full backup hash; never overwrites a file."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--directory',type=Path,default=Path('.'));a=p.parse_args();m=json.loads(a.manifest.read_text());target=a.directory/m['archive_name'];total=hashlib.sha256()
with target.open('xb') as out:
 for part in m['parts']:
  h=hashlib.sha256();size=0
  with (a.directory/part['name']).open('rb') as f:
   while b:=f.read(1024*1024):h.update(b);total.update(b);out.write(b);size+=len(b)
  if h.hexdigest()!=part['sha256'] or size!=part['bytes']:raise ValueError('Part checksum mismatch: '+part['name'])
if total.hexdigest()!=m['archive_sha256']:raise ValueError('Archive checksum mismatch')
print('Verified archive:',target)
