"""Actual indexed-query work on publicly built snapshots at two unrelated sizes."""
import json
import subprocess

from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def test_actual_reverse_queries_and_missing_name_under_growth(tmp_path):
    measurements = []
    for count in (0, 100):
        c, repo = initialize(tmp_path / f"fixture-{count}")
        (repo / "src/caller.py").write_text("from target import missing_name\n")
        (repo / "src/target.py").write_text("def existing(): pass\n")
        (repo / "src/noise_base.py").write_text("def helper(): pass\n")
        for i in range(count):
            (repo / f"src/noise_{i}.py").write_text("from noise_base import helper\nhelper()\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                        "commit", "-m", "fixture"], check=True, capture_output=True)
        result = build(c, offline=True, lexical_only=True)
        folder, meta = manifest(c, result["version"])
        with FileDependencies(folder, meta) as index:
            queries = []
            index.db.set_trace_callback(queries.append)
            row = {"unrelated_files": count, "calls": []}
            for label, operation in (
                ("reverse", lambda: index.adjacent("synthetic-review", "src/target.py")),
                ("importers", lambda: index.importers("synthetic-review", "target")),
            ):
                for temperature in ("cold", "repeat"):
                    steps = [0]
                    def tick():
                        steps[0] += 1
                        return 0
                    index.db.set_progress_handler(tick, 1)
                    found = operation()
                    index.db.set_progress_handler(None, 0)
                    assert found == {("synthetic-review", "src/caller.py")}
                    sql = queries[-1]
                    plan = [r[3] for r in index.db.execute("EXPLAIN QUERY PLAN " + sql)]
                    assert any("SEARCH" in p for p in plan)
                    assert not any("SCAN file_adjacency" in p or "SCAN import_requests" in p for p in plan)
                    row["calls"].append(dict(operation=label, temperature=temperature,
                                             vm_steps=steps[0], returned=len(found), plan=plan))
            index.db.set_trace_callback(None)
            measurements.append(row)
    assert [x["vm_steps"] for x in measurements[0]["calls"]] == [x["vm_steps"] for x in measurements[1]["calls"]]
    print(json.dumps(measurements, indent=2))
