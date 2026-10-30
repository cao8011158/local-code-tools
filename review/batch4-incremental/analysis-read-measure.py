"""Offline indexed SQL read contrast for 0/100 unrelated analysis records."""

import json
import sqlite3
import tempfile
from pathlib import Path

from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


root = Path(tempfile.mkdtemp(prefix="lct-analysis-read-measure-"))
config, repo = initialize(root / "fixture")
(repo / "src/weights.py").unlink()
(repo / "docs/guide.md").unlink()
(repo / "src/b.py").write_text(
    "def target(): pass\nregistry={'go':target}\n"
    "def run():\n    return registry['go']()\n")
sql = ("select consumer_repository,consumer_path from analysis_reads "
       "where producer_repository=? and producer_path=? and kind='container-effects'")
args = ("synthetic-review", "src/b.py")
for count in (0, 100):
    for number in range(count):
        path = repo / f"src/unrelated_{number}.py"
        if not path.exists():
            path.write_text(f"def f_{number}(): pass\n"
                            f"data={{'x':f_{number}}}\n"
                            "def run():\n    data['x']()\n")
    result = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, result["version"])
    with FileDependencies(folder, meta) as relations:
        plan = list(relations.db.execute("explain query plan " + sql, args))
        row_count = relations.db.execute("select count(*) from analysis_reads").fetchone()[0]
        vm = [0]
        relations.db.set_progress_handler(lambda: vm.__setitem__(0, vm[0] + 1), 1)
        try:
            rows = list(relations.db.execute(sql, args))
        finally:
            relations.db.set_progress_handler(None, 0)
    print(json.dumps(dict(unrelated_modules=count, total_read_rows=row_count,
                          target_rows=rows, query_vm_steps=vm[0],
                          sql_plan=[p[3] for p in plan]), sort_keys=True))
