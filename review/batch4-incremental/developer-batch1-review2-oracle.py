import json, sqlite3, tempfile
from pathlib import Path
from tests.synthetic_support import initialize
from lct.storage import build, manifest
observed={}
for argument in ('*values','**values',''):
    with tempfile.TemporaryDirectory() as temp:
        config, repo = initialize(Path(temp)/'fixture')
        (repo/'src/weights.py').unlink(); (repo/'docs/guide.md').unlink()
        (repo/'src/provider.py').write_text('from worker import execute\ndef provide(values): execute('+argument+')\n')
        (repo/'src/worker.py').write_text('def execute(callback): callback()\n')
        result=build(config,offline=True,lexical_only=True)
        folder, m=manifest(config,result['version'])
        with sqlite3.connect(folder/'graph-sites.sqlite') as db:
            sites=[json.loads(raw) for (raw,) in db.execute('select data from sites order by ordinal')]
        observed[argument]=sites
print(json.dumps(observed,sort_keys=True))
