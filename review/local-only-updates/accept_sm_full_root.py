"""Independent full83 warm acceptance; each invocation is a fresh process."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from lct.graph import Graph
from lct.query import Query
from lct.storage import build, current, manifest
from tests.synthetic_support import forbid_provider


def hashes(folder):
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in ("catalog.sqlite", "graph-sites.sqlite", "manifest.json")}


def inspect(c, version):
    folder, meta = manifest(c, version)
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = {ident: json.loads(raw) for ident, raw in db.execute("select node_id,data from nodes")}
        edges = [json.loads(raw) for raw, in db.execute("select data from edges")]
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        sites = [json.loads(raw) for raw, in db.execute("select data from sites")]
    return folder, meta, nodes, edges, sites


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--operation", choices=("numeric", "actor", "restore"), required=True)
    args = p.parse_args()
    c = json.loads((args.workspace / "acceptance-config.json").read_text())
    initial = json.loads((args.workspace / "first-build-result.json").read_text())
    baseline_version = initial["version"]
    old_version = current(c)
    baseline_folder, _, _, _, _ = inspect(c, baseline_version)
    old_hashes = hashes(baseline_folder)
    repo = Path(c["repositories"][0]["path"])
    numeric = repo / "src/trpg_state_machine/item_units.py"
    actor = repo / "src/trpg_state_machine/_execution.py"
    if args.operation == "numeric":
        raw = numeric.read_bytes()
        assert raw.count(b"2**63 - 1") == 1
        numeric.write_bytes(raw.replace(b"2**63 - 1", b"2**63 - 2"))
    elif args.operation == "actor":
        raw = actor.read_bytes()
        assert raw.count(b'"kind": "actor"') == 1
        actor.write_bytes(raw.replace(b'"kind": "actor"', b'"kind": "acting_actor"'))
    else:
        for path, before, after in ((numeric, b"2**63 - 2", b"2**63 - 1"),
                                    (actor, b'"kind": "acting_actor"', b'"kind": "actor"')):
            raw = path.read_bytes()
            assert raw.count(before) == 1
            path.write_bytes(raw.replace(before, after))
    calls = []
    real = Graph.build

    def watch(graph, *pos, **kw):
        chosen = kw.get("selected_owners")
        assert chosen is not None, "warm update entered the cold/full analyzer"
        calls.append(dict(selected=len(chosen), catalog_owners=len(graph.asts)))
        return real(graph, *pos, **kw)

    print(json.dumps(dict(stage="start", operation=args.operation, previous=old_version)), flush=True)
    start = time.monotonic()
    with forbid_provider(), patch.object(Graph, "build", watch):
        result = build(c, offline=True, lexical_only=True)
    scope = result["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["python_files_parsed"] == (2 if args.operation == "restore" else 1)
    folder, meta, nodes, edges, sites = inspect(c, result["version"])
    assert hashes(baseline_folder) == old_hashes, "previous snapshot changed"
    assert current(c) == result["version"]
    owner = next(i for i, n in nodes.items() if n["qualname"] == "_execution_data")
    error = next(i for i, n in nodes.items() if n["qualname"] == "StateMachineError")
    error_site = next(s for s in sites if s["execution_owner"] == owner
                      and s["expression"] == "StateMachineError")
    assert error in error_site["targets"], "real direct error constructor lost"
    assert any(e["source"] == owner and e["target"] == error and e["kind"] == "CALLS"
               for e in edges)
    query = Query(c)
    replies = []
    for _ in range(2):
        detail = query.get_nodes([owner], version=result["version"], max_bytes=8000)
        relations = query.get_relations([owner], ["CALLS"], version=result["version"], max_bytes=12000)
        assert detail["nodes"][0]["live_file_matches"] is True
        assert any(e["target"] == error for e in relations["edges"])
        replies.append(dict(node_bytes=len(json.dumps(detail).encode()),
                            relation_bytes=len(json.dumps(relations).encode()),
                            node_count=len(detail["nodes"]), edge_count=len(relations["edges"])))
    old_detail = query.get_nodes([owner], version=baseline_version, max_bytes=8000)
    assert old_detail["nodes"][0]["source_origin"] == "indexed_snapshot"
    assert replies[0] == replies[1]
    assert hashes(baseline_folder) == old_hashes
    summary = dict(operation=args.operation, process_id=os.getpid(), seconds=round(time.monotonic()-start, 3),
                   version=result["version"], previous=old_version, baseline=baseline_version,
                   graph_calls=calls, scope=scope, graph=result["graph"],
                   counts=dict(nodes=len(nodes), edges=len(edges), sites=len(sites)),
                   known_direct_call=dict(owner=owner, target=error,
                       complete=error_site["complete"], targets=error_site["targets"]),
                   reads=replies, old_snapshot_unchanged=True,
                   old_live_matches=old_detail["nodes"][0]["live_file_matches"])
    (args.workspace / (args.operation + "-result.json")).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
