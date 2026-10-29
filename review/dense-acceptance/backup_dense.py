"""Create a supported complete toolkit backup after real dense validation."""
import json,sys,zipfile,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from lct.common import config,atomic
from lct.management import backup
c=config('/tmp/lct-b3-isolated-v2-20261029/config.json')
assert json.loads((root/'review/dense-acceptance/retrieval-result.json').read_text())['exit_code']==0
r=backup(c);p=Path(r['archive']);r.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest())
with zipfile.ZipFile(p) as z:
 r['members']=len(z.namelist())
 assert not any('secret' in x.lower() or x.endswith('.env') for x in z.namelist())
 r['provider_credentials_included']=False
atomic(root/'review/dense-acceptance/backup.json',r);print(json.dumps(r))
