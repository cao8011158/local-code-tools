"""One bounded offline lexical build followed immediately by a supported backup."""
import argparse
import hashlib
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--config',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
result={'tool_commit':'5c413c4bceed0093f3054a913199607b74ae4495','paid_requests':0,'lexical_only':True,'steps':[]}
start=time.monotonic()
try:
    for name,tail,seconds in [('build',['build','--offline','--lexical-only'],480),('backup',['backup'],120)]:
        command=[sys.executable,str(root/'local_code_tools.py'),'--config',str(Path(args.config).resolve()),*tail]
        tick=time.monotonic()
        with (out/(name+'.stdout')).open('w') as stdout,(out/(name+'.stderr')).open('w') as stderr:
            run=subprocess.run(command,cwd=root,stdout=stdout,stderr=stderr,timeout=seconds)
        record={'step':name,'exit_code':run.returncode,'seconds':time.monotonic()-tick,'command':command}
        result['steps'].append(record)
        if run.returncode:raise RuntimeError(name+' failed; see stderr')
        raw=json.loads((out/(name+'.stdout')).read_text())
        record['result']=({k:raw[k] for k in ('version','state','node_count','edges','dense_ready','seconds','source_fingerprint','program_hash','config_hash')} if name=='build' else raw)
        if name=='build':record['result']['graph_summary']={k:v for k,v in raw['graph'].items() if k!='sites'}
        del raw
        print(json.dumps({'step':name,'seconds':record['seconds'],'result':record['result']},ensure_ascii=False),flush=True)
    archive=Path(result['steps'][1]['result']['archive'])
    h=hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    if h.hexdigest()!=result['steps'][1]['result']['sha256']:raise AssertionError('archive hash')
    result.update(status='PASS',archive=str(archive),archive_sha256=h.hexdigest(),archive_bytes=archive.stat().st_size)
except BaseException as error:
    result.update(status='FAIL',error=type(error).__name__+': '+str(error))
    raise
finally:
    result['elapsed_seconds']=time.monotonic()-start
    result['child_peak_rss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    (out/'build-backup-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
