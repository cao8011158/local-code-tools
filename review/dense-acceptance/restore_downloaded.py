"""Restore actual downloaded multipart archive with original data/sources unavailable."""
import json,sys,hashlib,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from lct.management import restore
out=root/'review/dense-acceptance';r=json.loads((out/'download-roundtrip.json').read_text());archive=Path(r['archive'])
assert hashlib.sha256(archive.read_bytes()).hexdigest()==r['sha256']
with zipfile.ZipFile(archive) as z:c=json.loads(z.read('config.json'))
source=Path('/workspace/scratch/413372d9a5a5/batch3-restored-sources');sh=source.with_name(source.name+'-dense-restore-held');data=Path(c['data']);dh=data.with_name('data-dense-restore-held');target=Path('/tmp/lct-b3-dense-drive-restored-20261029')
assert not target.exists() and not sh.exists() and not dh.exists()
e={'archive_sha256':r['sha256'],'paid_requests':0,'shared_installed_dependencies':True};ms=md=False
try:
 source.rename(sh);ms=True;data.rename(dh);md=True
 e['restore']=restore(c,archive,target)
 common=['--toolkit',str(target),'--config',str(target/'config.json')]
 cmd=[sys.executable,str(out/'verify.py'),*common,'--expected',str(root/'review/evaluation-expected.json'),'--output',str(out/'restored-observations.json'),'--compare',str(out/'original-observations.json'),'--baseline-version','20261029T111748-7a235bf36f','--baseline-nodes','5957','--baseline-edges','42492','--baseline-graph-sha256','1b220e9c80aca289ba2a7c86ffcf09d0a2cae9874310c96cd4bb2ebd2951e13b','--baseline-source-fingerprint','12fe107f9c97d29261ea06cfd60c5c0e72e0a6a93aac9abb3af63c156de052fd']
 p=subprocess.run(cmd,capture_output=True,text=True,timeout=120);e['dense']=dict(exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr);assert p.returncode==0,p.stderr
 cmd=[sys.executable,str(root/'review/business-resume/verify_restored_lexical.py'),*common,'--output',str(out/'lexical-restored.json'),'--expected',str(out/'lexical-before.json'),'--require-no-live']
 p=subprocess.run(cmd,capture_output=True,text=True,timeout=90);e['lexical']=dict(exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr);assert p.returncode==0,p.stderr
 assert not source.exists() and not data.exists();e.update(status='PASS',original_source_and_data_absent=True)
finally:
 if md:dh.rename(data)
 if ms:sh.rename(source)
 (out/'portable-acceptance.json').write_text(json.dumps(e,indent=2));print(json.dumps(e))
