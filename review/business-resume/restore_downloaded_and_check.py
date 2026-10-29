"""Restore downloaded toolkit without original index/source directories present."""
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from lct.management import restore
archive=Path('/workspace/scratch/413372d9a5a5/batch3-toolkit-drive-download.zip')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='f0bdb2309c9fc349207593bbd45d1ed6dce2df6cb967ee5516fa127acd96ae01'
with zipfile.ZipFile(archive) as z:c=json.loads(z.read('config.json'))
source=Path('/workspace/scratch/413372d9a5a5/batch3-restored-sources');source_hold=source.with_name('batch3-restored-sources-held')
data=Path(c['data']);data_hold=data.with_name('data-held-for-restore')
target=Path('/tmp/lct-b3-drive-restored-20261029')
assert not target.exists() and not source_hold.exists() and not data_hold.exists()
result={'archive_sha256':'f0bdb2309c9fc349207593bbd45d1ed6dce2df6cb967ee5516fa127acd96ae01','paid_requests':0,'shared_installed_dependencies':True}
moved_source=moved_data=False
try:
 source.rename(source_hold);moved_source=True
 data.rename(data_hold);moved_data=True
 assert not source.exists() and not data.exists()
 result['restore']=restore(c,archive,target)
 cmd=[sys.executable,str(root/'review/business-resume/verify_restored_lexical.py'),'--toolkit',str(target),'--config',str(target/'config.json'),'--output',str(root/'review/business-resume/lexical-after.json'),'--expected',str(root/'review/business-resume/lexical-before.json'),'--require-no-live']
 p=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
 result['verification_exit']=p.returncode;result['verification_stdout']=p.stdout;result['verification_stderr']=p.stderr
 assert p.returncode==0,p.stderr
 result.update(status='PASS',original_source_and_data_absent_during_restore=True)
finally:
 if moved_data:data_hold.rename(data)
 if moved_source:source_hold.rename(source)
 result['originals_restored']=source.exists() and data.exists()
 (root/'review/business-resume/portable-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
