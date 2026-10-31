"""Offline public-build measurement of 0/20/100 unrelated local writers."""

import json
import sqlite3
import tempfile
from pathlib import Path

from lct.storage import build, manifest
from tests.synthetic_support import initialize


root = Path(tempfile.mkdtemp(prefix="lct-slot-locality-"))
config, repo = initialize(root / "isolated")
(repo / "src/weights.py").unlink()
(repo / "docs/guide.md").unlink()
(repo / "src/b.py").write_text(
    "def target(): pass\nregistry={'go':target}\n"
    "def run():\n    return registry['go']()\n")
for count in (0, 20, 100):
    for number in range(count):
        path = repo / f"src/a_{number}.py"
        if not path.exists():
            path.write_text(f"def writer_{number}():\n"
                            "    slot={}\n    alias=slot\n    alias['x']=1\n")
    result = build(config, offline=True, lexical_only=True)
    folder, _ = manifest(config, result["version"])
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        site = next(json.loads(raw) for (raw,) in db.execute("select data from sites")
                    if '"expression":"registry[\'go\']"' in raw)
    graph = result["graph"]
    coverage = site["resolution_decision"]["write_source_coverage"]
    print(json.dumps(dict(unrelated_writer_scopes=count,
                          index_build_scopes=graph["slot_scope_index_build_scopes"],
                          fallback_scopes=graph["slot_scope_fallback_scopes"],
                          candidate_scopes_checked=graph["slot_scope_candidates_checked"],
                          events_checked=graph["slot_events_checked"],
                          consumer_required_events=len(coverage["required_events"]),
                          consumer_targets=site["targets"],
                          consumer_complete=site["complete"]), sort_keys=True))
