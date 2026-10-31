"""Measure the real public owner build, separating local solver and global costs."""
import argparse
import ast
import json
from pathlib import Path
import runpy
import sqlite3
import tempfile
import time
from unittest.mock import patch

from lct import extract as extraction, storage, unit_evidence
from lct.common import canonical, program_hash
from lct.python_analysis import Analyzer
from lct.query import Query

helpers = runpy.run_path(str(Path(__file__).with_name("test_owner_update_independent.py")))


def measure(root, noise):
    c, repo = helpers["fixture"](root, {
        "caller.py": helpers["CALLER"], "worker.py": helpers["WORKER"]}, noise)
    storage.build(c, offline=True, lexical_only=True)
    (repo / "src/caller.py").write_text(
        helpers["CALLER"].replace("execute(first)", "execute(second)"))
    counts = dict(inventory_calls=0, captured_files=0, captured_text_bytes=0,
                  parsed_files=0, ast_decode_calls=0, compressed_ast_bytes=0,
                  decoded_module_roots=0, module_inventory_calls=0,
                  mounted_files=0, mounted_utf8_bytes=0, artifact_hash_calls=0,
                  artifact_hash_bytes=0)
    real_inventory, real_parse = storage.inventory, extraction.python_nodes
    real_decode, real_hash = unit_evidence._decode_asts, storage.hash_artifact
    real_walk, real_write = Analyzer.inventory, Path.write_text

    def inventory(*args, **kwargs):
        result = real_inventory(*args, **kwargs)
        counts["inventory_calls"] += 1
        counts["captured_files"] += len(result[0])
        counts["captured_text_bytes"] += sum(len(f["text"].encode()) for f in result[0])
        return result

    def parse(*args, **kwargs):
        counts["parsed_files"] += 1
        return real_parse(*args, **kwargs)

    def decode(payload):
        result = real_decode(payload)
        counts["ast_decode_calls"] += 1
        counts["compressed_ast_bytes"] += len(payload)
        counts["decoded_module_roots"] += sum(isinstance(t, ast.Module) for t in result.values())
        return result

    def digest(*args, **kwargs):
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
            counts["mounted_utf8_bytes"] += len(text.encode("utf-8"))
        return result

    started = time.monotonic()
    with patch.object(storage, "inventory", inventory), patch.object(extraction, "python_nodes", parse), \
            patch.object(unit_evidence, "_decode_asts", decode), patch.object(storage, "hash_artifact", digest), \
            patch.object(Analyzer, "inventory", walk), patch.object(Path, "write_text", write):
        updated = storage.build(c, offline=True, lexical_only=True)
    elapsed = time.monotonic() - started
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert counts["parsed_files"] == scope["total_python_files_parsed"] == 1
    assert counts["inventory_calls"] == 2  # initial capture and final publication fence
    assert counts["ast_decode_calls"] == 1
    assert counts["captured_files"] == 2 * (noise + 2)
    assert counts["decoded_module_roots"] == noise + 2
    assert counts["module_inventory_calls"] == counts["mounted_files"] == noise + 2
    assert 2 * counts["mounted_utf8_bytes"] == counts["captured_text_bytes"]
    folder, meta = storage.manifest(c, updated["version"])
    with sqlite3.connect(folder / "catalog.sqlite") as db:
        worker = next(ident for ident, raw in db.execute("select node_id,data from nodes")
                      if json.loads(raw)["qualname"] == "execute")
    replies = []
    query = Query(c)
    for _ in range(2):  # cold object then repeated same-version public reads
        detail = query.get_nodes([worker], version=updated["version"])
        relations = query.get_relations([worker], ["CALLS"], version=updated["version"])
        replies.append(dict(node_reply_bytes=len(canonical(detail).encode()),
                            relation_reply_bytes=len(canonical(relations).encode()),
                            nodes=len(detail["nodes"]), edges=len(relations["edges"])))
    assert replies[0] == replies[1]
    helpers["oracle"](c, updated["version"], root)
    return dict(unrelated_active_files=noise, capture_modules=noise + 2,
                seconds_with_measurement=elapsed, actual_work=counts,
                solver={k: scope[k] for k in ("selected_owner_count", "owner_jedi_queries_executed",
                        "owner_association_evaluations", "sites_analyzed")},
                snapshot_materialized_bytes=sum(meta["artifact_sizes"].values()),
                snapshot_artifacts=meta["artifact_sizes"], public_reads=replies)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lct-owner-work-") as temp:
        rows = [measure(Path(temp) / str(n), n) for n in (0, 20, 100)]
    assert rows[0]["solver"] == rows[1]["solver"] == rows[2]["solver"]
    assert rows[0]["snapshot_materialized_bytes"] < rows[1]["snapshot_materialized_bytes"] < rows[2]["snapshot_materialized_bytes"]
    result = dict(program_hash=program_hash(), measurements=rows,
                  limitations=["Two inventories are initial capture plus the final publication fence; text bytes are returned observations, not all filesystem reads.",
                               "storage.hash_artifact counts its actual streamed bytes including repeated validation; other source/metadata digest work is not claimed.",
                               "Mount/AST/output costs are full-capture work; only solver work is local.",
                               "Transparent measurement overhead is included; no wall-clock threshold."])
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
