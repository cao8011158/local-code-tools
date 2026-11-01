import json,tempfile
from pathlib import Path
from lct.storage import build
from tests.synthetic_support import initialize,forbid_provider
for n in (0,20,100):
 with tempfile.TemporaryDirectory() as td:
  c,repo=initialize(Path(td)/'case');(repo/'src/weights.py').unlink();(repo/'docs/guide.md').unlink()
  (repo/'src/utility.py').write_text('def noop():pass\n')
  for i in range(n):(repo/f'src/noise_{i}.py').write_text(f'from utility import noop\ndef idle_{i}():noop()\n')
  p=repo/'src/active.py'
  def source(t):return 'def first():pass\ndef second():pass\nhandlers={"go":'+t+'}\ndef run():handlers["go"]()\n'
  p.write_text(source('first'))
  with forbid_provider():cold=build(c,offline=True,lexical_only=True)
  p.write_text(source('second'))
  with forbid_provider():warm=build(c,offline=True,lexical_only=True)
  print(json.dumps(dict(noise=n,mode=warm['incremental']['analysis_scope']['mode'],owners=warm['incremental']['analysis_scope']['selected_owner_count'],jedi=warm['graph']['jedi_queries_executed'],entries=warm['graph']['jedi_query_entries'],callprep=warm['graph'].get('slot_call_index_events'),read_events=warm['graph']['slot_events_checked'])),flush=True)
