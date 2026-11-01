"""Root acceptance harness: static analysis of exact pinned SM sources, no execution."""
import argparse
import faulthandler
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

from lct.storage import build, manifest
from tests.synthetic_support import forbid_provider, initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    provenance = json.loads((args.source / "SOURCE_PROVENANCE.json").read_text())
    c, repo = initialize(args.workspace)
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for relative, expected in provenance["files"].items():
        raw = (args.source / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == expected["git_blob"]
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.source / relative, destination)
    c["retained_versions"] = 8
    c["embedding"].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    (args.workspace / "acceptance-config.json").write_text(json.dumps(c, indent=2))
    print(json.dumps(dict(stage="start", files=len(provenance["files"]),
                          source_commit=provenance["commit"])), flush=True)
    started = time.monotonic()
    if args.trace:
        faulthandler.dump_traceback_later(15, repeat=True)
    with forbid_provider():
        result = build(c, offline=True, lexical_only=True)
    folder, metadata = manifest(c, result["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        counts = {table: db.execute("select count(*) from " + table).fetchone()[0]
                  for table in ("nodes", "edges")}
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        counts.update({table: db.execute("select count(*) from " + table).fetchone()[0]
                       for table in ("sites", "unit_source_supports", "unit_container_subscriptions",
                                     "unit_container_writes", "unit_analysis_reads", "unit_input_events")})
        availability = [json.loads(raw) for raw, in db.execute("select data from sites")
                        if "AvailabilityRuntime.query_action_availability#" in raw]
    output = dict(seconds=round(time.monotonic()-started, 3), counts=counts,
                  graph=result["graph"], version=result["version"],
                  availability=[{key:s.get(key) for key in ("expression", "targets", "complete",
                                                           "unknown_origin", "unresolved_reasons")}
                                for s in availability])
    (args.workspace / "first-build-result.json").write_text(json.dumps(output, indent=2))
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
