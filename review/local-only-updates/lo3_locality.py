"""Public warm owner update and indexed reverse-query growth evidence."""

import argparse
import ast
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from lct import extract as extraction, storage, unit_evidence
from lct.common import canonical, program_hash
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.query import Query
from tests.synthetic_support import forbid_provider, initialize

PROVIDER = ("def first(): pass\ndef second(): pass\n"
            "class Base:\n    def handle(self): pass\n"
            "registry={'go':first}\n")
CONSUMER = ("from provider import first, registry, Base\n"
            "def direct(): first()\n"
            "def run(): registry['go']()\n"
            "class Runner(Base):\n    def method(self): self.handle()\n")


def fixture(root, noise):
    c, repo = initialize(root)
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    c["retained_versions"] = 8
    (repo / "src/provider.py").write_text(PROVIDER)
    (repo / "src/consumer.py").write_text(CONSUMER)
    for i in range(noise):
        (repo / f"src/noise_{i:03d}.py").write_text(
            f"def other_{i}(): pass\nregistry={{'go':other_{i}}}\n"
            f"def use_{i}(): registry['go']()\n")
    return c, repo


def index_probe(folder, meta, nodes):
    ids = {n["qualname"]: n["node_id"] for n in nodes if n["kind"] in {"module", "class", "function"}}
    with storage.FileDependencies(folder, meta) as deps:
        origins = [json.loads(raw)["origin"] for (raw,) in deps.db.execute(
            "select data from unit_container_subscriptions where consumer_owner=?",
            (ids["run"],))]
        assert origins
        origin = next(o for o in origins if ":provider#" in o)
        phases = []
        for _ in range(2):
            sql, ticks = [], [0]
            def tick():
                ticks[0] += 1
                return 0
            deps.db.set_trace_callback(sql.append)
            deps.db.set_progress_handler(tick, 1)
            call = deps.unit_readers(ids["first"])
            receiver = deps.unit_readers(ids["Runner"])
            container = deps.unit_container_readers(origin, "go")
            deps.db.set_progress_handler(None, 0)
            deps.db.set_trace_callback(None)
            plans = [[r[3] for r in deps.db.execute("EXPLAIN QUERY PLAN " + statement)]
                     for statement in sql]
            assert {owner for owner, _ in call} == {ids["direct"]}
            assert {owner for owner, _ in receiver} == {ids["Runner.method"]}
            assert {row["consumer_owner"] for row in container} == {ids["run"]}
            assert all(any("SEARCH" in line and "INDEX" in line for line in plan)
                       and not any("SCAN" in line for line in plan) for plan in plans), plans
            phases.append(dict(vm_steps=ticks[0], sql_count=len(sql),
                               rows=dict(call=len(call), receiver=len(receiver),
                                         container=len(container)), plans=plans))
        assert phases[0]["sql_count"] == phases[1]["sql_count"]
        return dict(origin=origin, phases=phases)


def measure(root, noise):
    c, repo = fixture(root, noise)
    with forbid_provider():
        first = storage.build(c, offline=True, lexical_only=True)
    old_version = first["version"]
    old_query = Query(c)
    (repo / "src/provider.py").write_text(PROVIDER.replace("registry={'go':first}",
                                                            "registry={'go':second}"))
    counts = dict(inventory_calls=0, captured_files=0, captured_text_bytes=0,
                  parsed_python_files=0, ast_decode_calls=0, compressed_ast_bytes=0,
                  decoded_module_roots=0, module_inventory_calls=0,
                  mounted_files=0, mounted_utf8_bytes=0, artifact_hash_calls=0,
                  artifact_hash_bytes=0, graph_selected_calls=0)
    real_inventory, real_parse = storage.inventory, extraction.python_nodes
    real_decode, real_hash = unit_evidence._decode_asts, storage.hash_artifact
    real_walk, real_write, real_graph = Analyzer.inventory, Path.write_text, Graph.build
    def inventory(*args, **kwargs):
        result = real_inventory(*args, **kwargs)
        counts["inventory_calls"] += 1
        counts["captured_files"] += len(result[0])
        counts["captured_text_bytes"] += sum(len(f["text"].encode()) for f in result[0])
        return result
    def parse(*args, **kwargs):
        counts["parsed_python_files"] += 1
        return real_parse(*args, **kwargs)
    def decode(payload):
        result = real_decode(payload)
        counts["ast_decode_calls"] += 1
        counts["compressed_ast_bytes"] += len(payload)
        counts["decoded_module_roots"] += sum(isinstance(t, ast.Module) for t in result.values())
        return result
    def hashed(*args, **kwargs):
        result = real_hash(*args, **kwargs)
        counts["artifact_hash_calls"] += 1
        counts["artifact_hash_bytes"] += result[1]
        return result
    def walk(self, obj, *args, **kwargs):
        if isinstance(obj, ast.Module):
            counts["module_inventory_calls"] += 1
        return real_walk(self, obj, *args, **kwargs)
    def write(path, text, *args, **kwargs):
        result = real_write(path, text, *args, **kwargs)
        if any(part.startswith("lct-python-") for part in path.parts):
            counts["mounted_files"] += 1
            counts["mounted_utf8_bytes"] += len(text.encode())
        return result
    def selected(graph, *args, **kwargs):
        assert kwargs.get("selected_owners") is not None
        counts["graph_selected_calls"] += 1
        return real_graph(graph, *args, **kwargs)
    started = time.monotonic()
    with forbid_provider(), patch.object(storage, "inventory", inventory), \
            patch.object(extraction, "python_nodes", parse), \
            patch.object(unit_evidence, "_decode_asts", decode), \
            patch.object(storage, "hash_artifact", hashed), \
            patch.object(Analyzer, "inventory", walk), \
            patch.object(Path, "write_text", write), patch.object(Graph, "build", selected):
        updated = storage.build(c, offline=True, lexical_only=True)
    elapsed = time.monotonic() - started
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners" and counts["graph_selected_calls"] >= 1
    assert counts["parsed_python_files"] == scope["total_python_files_parsed"] == 1
    assert counts["inventory_calls"] == 2
    assert counts["ast_decode_calls"] == 1
    assert counts["decoded_module_roots"] == counts["module_inventory_calls"] == noise + 2
    assert counts["mounted_files"] == noise + 2
    assert counts["captured_files"] == 2 * (noise + 2)
    folder, meta = storage.manifest(c, updated["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        nodes = [json.loads(raw) for (raw,) in db.execute("select data from nodes")]
    ids = {n["qualname"]: n["node_id"] for n in nodes if n["kind"] in {"module", "class", "function"}}
    q = Query(c)
    replies = []
    for _ in range(2):
        detail = q.get_nodes([ids["run"]], version=updated["version"])
        related = q.get_relations([ids["run"]], ["CALLS"], version=updated["version"])
        replies.append(dict(nodes=len(detail["nodes"]), edges=len(related["edges"]),
                            node_bytes=len(canonical(detail).encode()),
                            relation_bytes=len(canonical(related).encode())))
    assert replies[0] == replies[1]
    old = old_query.get_nodes([ids["run"]], version=old_version)
    assert old["version"] == old_version and storage.current(c) == updated["version"]
    reverse = index_probe(folder, meta, nodes)
    assert all(":function:use_" not in owner for owner in scope["selected_owner_ids"])
    return dict(noise=noise, elapsed_seconds=elapsed, capture=counts,
                solver={k: scope[k] for k in ("selected_owner_count", "reused_owner_count",
                    "owner_jedi_queries_executed", "owner_association_evaluations", "sites_analyzed",
                    "slot_scope_index_build_scopes", "slot_scope_candidates_checked") if k in scope},
                artifact_bytes=sum(meta["artifact_sizes"].values()),
                public_reads=replies, old_view_bytes=len(canonical(old).encode()),
                reverse=reverse)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lct-lo3-locality-") as tmp:
        rows = [measure(Path(tmp) / str(n), n) for n in (0, 20, 100)]
    constant = ("selected_owner_count", "owner_jedi_queries_executed",
                "owner_association_evaluations", "sites_analyzed", "slot_scope_candidates_checked")
    assert all(tuple(row["solver"].get(k) for k in constant) ==
               tuple(rows[0]["solver"].get(k) for k in constant) for row in rows)
    assert rows[0]["artifact_bytes"] < rows[1]["artifact_bytes"] < rows[2]["artifact_bytes"]
    assert rows[1]["reverse"]["phases"] == rows[2]["reverse"]["phases"]
    result = dict(program_hash=program_hash(), rows=rows,
                  limits=["Capture, hash, AST decode, effect index, mounting and artifact writes grow with all input; solver counters stay local.",
                          "SQLite VM steps count actual selected reverse queries, not entire publication or query serialization.",
                          "Timing includes measurement wrappers; no wall-time threshold or claim about 83-file full acceptance."])
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
