"""Migrate an owned copy, measure real public I/O, restore; never parse or embed."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lct.common import canonical, config, program_hash
from lct.embedding import Embeddings
from lct.management import backup, restore
from lct.query import Query
from lct.storage import manifest, migrate_metadata, graph_detail, source_files

OUT = ROOT / 'review/official-mcp-transition'
C = config('/tmp/lct-b3-isolated-v2-20261029/config.json')
DATA = Path(C['data'])
HELD = DATA.with_name('data-original-held-official')
COPY = Path('/tmp/lct-official-mcp-data')
TARGET = Path('/tmp/lct-official-mcp-restored')
SOURCE = Path('/workspace/scratch/413372d9a5a5/batch3-restored-sources')
SOURCE_HELD = SOURCE.with_name('batch3-restored-sources-official-held')
E = {'status': 'RUNNING', 'program_hash': program_hash(), 'paid_requests': 0}

def deny(*a, **kw):
    raise AssertionError('Embedding calls prohibited')
Embeddings.call = deny
os.environ.pop('VOYAGE_API_KEY', None)

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def run(command, name):
    p = subprocess.run(command, capture_output=True, text=True, timeout=180)
    (OUT / (name + '.log')).write_text(p.stdout + p.stderr)
    assert p.returncode == 0, (name, p.stderr[-2000:], p.stdout[-1000:])

assert not any(p.exists() for p in (HELD, COPY, TARGET, SOURCE_HELD))
shutil.copytree(DATA, COPY, ignore=shutil.ignore_patterns('backups', '*.lock'))
preserved = {str(p.relative_to(DATA)): sha(p) for p in DATA.rglob('*')
             if p.is_file() and 'backups' not in p.parts}
moved = source_moved = False
try:
    DATA.rename(HELD); moved = True
    COPY.rename(DATA)
    E['migration'] = []
    for folder in sorted((DATA / 'versions').iterdir()):
        old = json.loads((folder / 'manifest.json').read_text())
        E['migration'].append(migrate_metadata(C, folder.name, old['program_hash']))
        _, m = manifest(C, folder.name)
        assert graph_detail(folder, m) == old['graph']
        assert source_files(folder, m) == old['files']
    folder, m = manifest(C)
    assert sha(folder / 'catalog.sqlite') == '7d260089cb4cfa45f4105509cb10283bbc2fd48504b54cebfad92ff61e2508e4'
    assert hashlib.sha256(canonical(graph_detail(folder, m)).encode()).hexdigest() == '1b220e9c80aca289ba2a7c86ffcf09d0a2cae9874310c96cd4bb2ebd2951e13b'
    E['graph_unchanged'] = True
    q = Query(C)
    nid = q.search_code('ContainerService current_weight', mode='bm25', limit=1)['results'][0]['node_id']
    original_read = Path.read_text
    reads = []
    def counted(path, *a, **kw):
        reads.append({'file':path.name, 'bytes':path.stat().st_size})
        assert path.name not in ('manifest.json', 'source-files.json')
        return original_read(path, *a, **kw)
    q = Query(C); observations=[]
    Path.read_text = counted
    try:
        for cycle in ('cold', 'warm'):
            for name, call in (
                ('index_status', lambda:q.index_status()),
                ('get_nodes', lambda:q.get_nodes([nid],include_source=False)),
                ('search_code',lambda:q.search_code('ContainerService current_weight',mode='bm25',limit=1)),
                ('search_docs',lambda:q.search_docs('snapshot',limit=1)),
                ('get_relations',lambda:q.get_relations([nid],max_edges=1)),
                ('graph_evidence',lambda:q.graph_evidence(limit=1))):
                reads.clear(); start=time.monotonic(); result=call()
                observations.append(dict(cycle=cycle, interface=name, reads=list(reads),
                    reply_bytes=len(canonical(result).encode()), seconds=time.monotonic()-start))
    finally: Path.read_text = original_read
    E['observations']=observations
    run([sys.executable,str(ROOT/'review/query-locality-repair/mcp_actual.py'),str(ROOT),C['_path'],str(OUT/'real-mcp.json')], 'real-mcp')
    package = backup(C)
    archive = Path('/tmp/lct-official-mcp-toolkit.zip')
    shutil.copyfile(package['archive'],archive)
    package['archive']=str(archive); E['backup']=package
    E['restore']=restore(C,archive,TARGET)
    # Original sources unavailable; both data and code used by MCP come from restored package.
    SOURCE.rename(SOURCE_HELD); source_moved=True
    run([sys.executable,str(ROOT/'review/query-locality-repair/mcp_actual.py'),str(TARGET),str(TARGET/'config.json'),str(OUT/'restored-mcp.json')], 'restored-mcp')
    E['status']='PASS'
finally:
    if source_moved: SOURCE_HELD.rename(SOURCE)
    if moved:
        DATA.rename(COPY)
        HELD.rename(DATA)
    E['original_data_unchanged']=all((DATA/rel).is_file() and sha(DATA/rel)==h for rel,h in preserved.items())
    (OUT/'real-acceptance.json').write_text(json.dumps(E,indent=2))
    print(json.dumps(E,indent=2))
