"""Independent boundary checks for frozen dense attachment; synthetic data, no API."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from lct.common import ToolError,atomic,identity,program_hash
from lct.storage import attach_dense,current,manifest
from tests.test_attach_dense import lexical_fixture
from tests.synthetic_support import forbid_provider

@pytest.mark.parametrize('field,value',[('template','wrong-template'),('schema',-99),('config_hash','wrong-config'),('embedding',{'model':'wrong'}),('hnsw',{})])
def test_explicit_program_approval_never_waives_format_config(tmp_path,field,value):
 c,_,old=lexical_fixture(tmp_path)
 folder,_=manifest(c)
 bad=dict(old);bad[field]=value;atomic(folder/'manifest.json',bad)
 with forbid_provider(),pytest.raises(ToolError,match='incompatible'):
  attach_dense(c,old['version'],offline=True,expected_program_hash=old['program_hash'])
 assert current(c)==old['version']

def test_catalog_tamper_rejected_before_embedding(tmp_path,monkeypatch):
 c,_,old=lexical_fixture(tmp_path);folder,_=manifest(c)
 with (folder/'catalog.sqlite').open('ab') as h:h.write(b'corrupt')
 def forbidden(*a,**k):raise AssertionError('Must reject before cache/provider access')
 monkeypatch.setattr('lct.storage.Embeddings',forbidden)
 with pytest.raises(ToolError,match='checksum'):
  attach_dense(c,old['version'],offline=True)
 assert current(c)==old['version']

def test_explicit_known_program_migration_is_recorded(tmp_path,monkeypatch):
 c,_,old=lexical_fixture(tmp_path)
 monkeypatch.setattr('lct.storage.program_hash',lambda:'1'*64)
 with forbid_provider():new=attach_dense(c,old['version'],offline=True,expected_program_hash=old['program_hash'])
 assert new['program_hash']=='1'*64
 assert new['incremental']['previous']==old['version']
 assert new['source_fingerprint']==old['source_fingerprint']
 assert new['artifacts']['catalog.sqlite']==old['artifacts']['catalog.sqlite']

def test_actual_cli_offline_migration(tmp_path):
 c,repo,old=lexical_fixture(tmp_path)
 repo.rename(repo.with_name('not-live'))
 p=subprocess.run([sys.executable,'-m','lct.cli','--config',c['_path'],'attach-dense','--version',old['version'],'--expected-program-hash',old['program_hash'],'--offline'],capture_output=True,text=True,timeout=30)
 assert p.returncode==0,p.stderr
 m=json.loads(p.stdout)
 assert m['dense_ready'] and m['version']==current(c)
 assert m['graph']==old['graph']
