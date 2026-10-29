"""Offline, independent observation of a *published* real dense index.

Run with the toolkit's Python environment. Never builds, embeds, or modifies source.
The only override forbids outbound embedding calls; it supplies no vectors or results.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np


def run(args):
    sys.path.insert(0, str(args.toolkit.resolve()))
    from lct.common import canonical, config
    from lct.embedding import Embeddings, vector_key
    from lct.query import Query
    from lct.storage import manifest, validate_folder, graph_detail

    def deny(*_args, **_kwargs):
        raise AssertionError("No embedding API is permitted during acceptance")

    Embeddings.call = deny
    os.environ.pop("VOYAGE_API_KEY", None)
    c = config(args.config)
    folder, m = manifest(c)
    validate_folder(folder, m)
    assert m["dense_ready"] and m["partitions"] and m["vector_chunks"] > 0, "No published dense index"
    assert m["version"] != args.baseline_version, "Expected a new published version"
    assert m["node_count"] == args.baseline_nodes and sum(m["edges"].values()) == args.baseline_edges
    assert hashlib.sha256(canonical(graph_detail(folder, m)).encode()).hexdigest() == args.baseline_graph_sha256
    assert m["source_fingerprint"] == args.baseline_source_fingerprint

    cases = json.loads(args.expected.read_text(encoding="utf-8"))["cases"]
    with sqlite3.connect((Path(c["data"]) / "vectors.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        cached = {}
        for case in cases:
            key = vector_key(c["embedding"], case["query"], "query")
            row = db.execute("select vector from vectors where key=?", (key,)).fetchone()
            assert row, f"Missing actual cached query vector: {case['id']}"
            v = np.frombuffer(row[0], dtype=np.float32)
            assert v.shape == (1024,) and np.isfinite(v).all() and np.linalg.norm(v) > 0
            cached[case["id"]] = v / np.linalg.norm(v)

    q = Query(c)
    records = []
    recalls = []
    for case in cases:
        levels = ("module", "class", "function") if case["level"] == "all" else (case["level"],)
        for level in levels:
            for k in (10, 50):
                approx = q.dense(folder, m, cached[case["id"]], level, [case["repo"]], k)
                exact = q.dense(folder, m, cached[case["id"]], level, [case["repo"]], k, exact=True)
                assert len(approx) == len(exact), (case["id"], level, k)
                recalls.append(dict(case=case["id"], level=level, k=k,
                                    recall=len(set(approx) & set(exact)) / len(exact) if exact else 1.0,
                                    exact_count=len(exact)))
        modes = {}
        for mode in ("bm25", "dense", "rrf"):
            result = q.search_code(case["query"], level=case["level"], repositories=[case["repo"]],
                                   mode=mode, candidates=50, limit=50)
            assert result["version"] == m["version"]
            rows = result["results"]
            assert all(x["repository"] == case["repo"] and
                       (case["level"] == "all" or x["kind"] == case["level"]) for x in rows)
            if mode == "rrf":
                for x in rows:
                    ranks = x["ranks"]
                    assert ranks["bm25"] is not None or ranks["dense"] is not None
                    assert x["bm25_unique_in_candidates"] == (ranks["bm25"] is not None and ranks["dense"] is None)
            modes[mode] = [dict(node_id=x["node_id"], path=x["path"], qualname=x["qualname"],
                                kind=x["kind"], ranks=x["ranks"]) for x in rows]
        label_ranks = {}
        if case.get("expected_name") or case.get("expected_path"):
            for mode, rows in modes.items():
                label_ranks[mode] = [i for i, x in enumerate(rows, 1)
                                     if (not case.get("expected_name") or x["qualname"] == case["expected_name"])
                                     and (not case.get("expected_path") or x["path"] == case["expected_path"])]
        records.append(dict(case=case["id"], label_ranks=label_ranks, modes=modes))

    mean = float(np.mean([r["recall"] for r in recalls]))
    minimum = min(r["recall"] for r in recalls)
    assert mean >= .95 and minimum >= .8, (mean, minimum)
    result = dict(version=m["version"], source_fingerprint=m["source_fingerprint"],
                  graph_sha256=hashlib.sha256(canonical(graph_detail(folder, m)).encode()).hexdigest(),
                  node_count=m["node_count"], edge_count=sum(m["edges"].values()),
                  vector_chunks=m["vector_chunks"], partitions=m["partitions"],
                  artifact_sha256=m["artifacts"], hnsw=m["hnsw"],
                  mean_recall=mean, minimum_recall=minimum, recalls=recalls, cases=records,
                  no_embedding_api=True)
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        assert {k:v for k,v in result.items() if k!="artifact_sha256"} == {k:v for k,v in before.items() if k!="artifact_sha256"} and all(result["artifact_sha256"].get(k)==v for k,v in before["artifact_sha256"].items()), "Restored retrieval/index evidence differs from original"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status="PASS", version=m["version"], cases=len(records),
                          comparisons=len(recalls), mean_recall=mean, minimum_recall=minimum,
                          compared_restore=bool(args.compare))))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--toolkit", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--expected", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--baseline-version", required=True)
    p.add_argument("--baseline-nodes", type=int, required=True)
    p.add_argument("--baseline-edges", type=int, required=True)
    p.add_argument("--baseline-graph-sha256", required=True)
    p.add_argument("--baseline-source-fingerprint", required=True)
    p.add_argument("--compare", type=Path)
    run(p.parse_args())
