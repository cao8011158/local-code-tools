"""Measure actual SQLite VM work after index open; source setup costs are separate."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize

results = []
for noise in [0, 100]:
    with TemporaryDirectory() as tmp:
        config, repo = initialize(Path(tmp) / 'fixture')
        (repo / 'src/weights.py').unlink()
        (repo / 'src/caller.py').write_text('from pkg import foo as alias\n')
        for number in range(noise):
            (repo / f'src/noise_{number}.py').write_text(f'from unrelated_{number} import missing\n')
        snapshot = build(config, offline=True, lexical_only=True)
        folder, meta = manifest(config, snapshot['version'])
        with FileDependencies(folder, meta) as deps:
            statements = []
            steps = [0]
            def step():
                steps[0] += 1
                return 0
            deps.db.set_trace_callback(statements.append)
            deps.db.set_progress_handler(step, 1)
            targets = deps.importers('synthetic-review', 'pkg.foo')
            requesters = deps.requesters('synthetic-review', 'pkg.foo')
            deps.db.set_progress_handler(None, 0)
            deps.db.set_trace_callback(None)
            plans = [[row[3] for row in deps.db.execute('explain query plan ' + sql)] for sql in statements]
            assert targets == requesters == {('synthetic-review', 'src/caller.py')}
            assert all('SEARCH' in ' '.join(plan) and 'SCAN' not in ' '.join(plan) for plan in plans)
            results.append(dict(noise=noise, query_count=len(statements), vm_steps=steps[0], result_rows=[len(targets),len(requesters)], plans=plans))
print(json.dumps(results, ensure_ascii=False, indent=2))
