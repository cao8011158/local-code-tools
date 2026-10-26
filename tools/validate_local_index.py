"""Validate an existing real local index without rebuilding, cache writes or Embedding API.

The production query/MCP code runs against authentic cached vectors via mode=ro
acceptance I/O. Output is compact evidence, not a real index or independent review.
"""

import argparse
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from lct.common import (  # noqa: E402
    ROOT,
    canonical,
    config,
    digest,
    git,
    inventory,
    load,
    now,
    program_hash,
)
from lct.embedding import Embeddings  # noqa: E402
from lct.query import Query  # noqa: E402
from lct.storage import manifest  # noqa: E402
from tools.readonly_cache import readonly_embeddings  # noqa: E402


def file_hash(path):
    """Stream hashes without materializing the catalog or changing any database."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def compact(row):
    """Keep a bounded result example; never serialize the node directory or vectors."""
    return {k: row.get(k) for k in ("node_id", "kind", "qualname", "path", "start", "end", "ranks")}


def mcp_check(c, output_dir):
    """Real initialize/list/call protocol with a provider-forbidden read-only I/O guard."""
    environment = dict(os.environ)
    environment.pop("VOYAGE_API_KEY", None)
    environment["LCT_CONFIG"] = c["_path"]
    log = (output_dir / "mcp-stderr.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/mcp_readonly_entry.py")],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        text=True,
        encoding="utf-8",
    )
    responses = queue.Queue()

    def reader():
        for line in proc.stdout:
            try:
                responses.put(json.loads(line))
            except ValueError:
                responses.put({"invalid_protocol_stdout": True})

    threading.Thread(target=reader, daemon=True).start()
    sequence = 0
    calls = []

    def request(method, params=None, notification=False):
        nonlocal sequence
        sequence += 1
        value = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            value["id"] = sequence
        proc.stdin.write(json.dumps(value) + "\n")
        proc.stdin.flush()
        if notification:
            return None
        while True:
            response = responses.get(timeout=30)
            assert not response.get("invalid_protocol_stdout")
            if response.get("id") == sequence:
                assert "error" not in response, response
                return response["result"]

    def call(name, args):
        value = request("tools/call", {"name": name, "arguments": args})
        assert not value.get("isError"), name
        result = value.get("structuredContent")
        if result is None:
            result = json.loads(next(x["text"] for x in value["content"] if x["type"] == "text"))
        calls.append({"name": name, "status": "passed", "arguments": args})
        return result

    try:
        hello = request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "source-only-review", "version": "1"},
            },
        )
        request("notifications/initialized", notification=True)
        names = [t["name"] for t in request("tools/list")["tools"]]
        assert set(names) == {
            "index_status",
            "search_code",
            "search_docs",
            "get_nodes",
            "get_relations",
        }
        status = call("index_status", {"refresh": False})
        assert status["dense_ready"]
        code = None
        for level, query, mode in (
            ("module", "world_containers ContainerService weights", "dense"),
            ("class", "ContainerService", "rrf"),
            ("function", "ContainerService current_weight", "bm25"),
        ):
            code = call(
                "search_code",
                {
                    "query": query,
                    "level": level,
                    "repositories": ["trpg-state-machine"],
                    "mode": mode,
                    "limit": 1,
                },
            )
            assert code["results"][0]["kind"] == level
        assert call(
            "search_docs", {"query": "实例字段 局部准入", "category": "contract", "limit": 1}
        )["results"]
        nid = code["results"][0]["node_id"]
        nodes = call("get_nodes", {"node_ids": [nid], "version": code["version"]})
        assert nodes["nodes"][0]["live_file_matches"]
        relations = call(
            "get_relations",
            {
                "node_ids": [nid],
                "relation_types": ["CALLS", "CONTAINS"],
                "direction": "both",
                "depth": 1,
                "max_edges": 10,
            },
        )
        assert relations["edges"]
        return {
            "status": "passed",
            "server": hello["serverInfo"],
            "tools": names,
            "calls": calls,
            "index_version": status["version"],
            "api_guard": "mode=ro existing cache; provider calls forbidden",
            "protocol_only_stdout": True,
        }
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
        log.close()


def validate(c, output_dir):
    """Run existing-index checks; changes/deletes/recovery belong to isolated tests only."""
    folder, m = manifest(c)
    assert (Path(c["data"]) / "cursor-key.json").is_file(), (
        "Existing cursor key required; no creation allowed"
    )
    protected = [
        Path(c["data"]) / "current.json",
        Path(c["data"]) / "ledger.json",
        Path(c["data"]) / "vectors.sqlite",
        Path(c["_path"]),
    ] + [folder / p for p in m["artifacts"]]
    before = {str(p): file_hash(p) for p in protected}
    result = {
        "generated_at": now(),
        "source_commit_tested": git(ROOT, "rev-parse", "HEAD"),
        "runtime_program_hash": program_hash(),
        "runtime_program_matches_index": program_hash() == m["program_hash"],
        "index": {
            k: m[k]
            for k in (
                "version",
                "toolkit_version",
                "schema",
                "format",
                "template",
                "tokenizer",
                "embedding",
                "metric",
                "hnsw",
                "source_fingerprint",
                "nodes",
                "edges",
                "call_resolution",
            )
        },
        "checks": {},
        "observations": [],
        "retrieval_is_independent_review": False,
    }
    files, repos, source_root = inventory(c)
    result["index"]["current_source_matches_index"] = source_root == m["source_fingerprint"]
    for repo in repos:
        indexed = next(r for r in m["repositories"] if r["name"] == repo["name"])
        repo["indexed_head"] = indexed["head"]
        repo["included_content_sha256"] = digest(
            canonical([(f["path"], f["sha256"]) for f in files if f["repository"] == repo["name"]])
        )
    result["repositories"] = repos
    q = Query(c)
    cases = load(ROOT / "review/evaluation-expected.json")["cases"]
    comparisons = []
    with readonly_embeddings():
        for case in cases:
            for mode in ("bm25", "dense", "rrf"):
                found = q.search_code(case["query"], case["level"], [case["repo"]], mode, 50, 10)
                rows = found["results"]
                assert all(n["repository"] == case["repo"] for n in rows)
                assert case["level"] == "all" or all(n["kind"] == case["level"] for n in rows)
                defined = bool(case.get("expected_name") or case.get("expected_path"))
                hits = [
                    i
                    for i, n in enumerate(rows, 1)
                    if (not case.get("expected_name") or n["qualname"] == case["expected_name"])
                    and (not case.get("expected_path") or n["path"] == case["expected_path"])
                ]
                result["observations"].append(
                    {
                        "case": case["id"],
                        "mode": mode,
                        "execution_status": "passed",
                        "result_count": len(rows),
                        "expected_entry_rank_top10": hits[0] if defined and hits else None,
                        "expected_entry_defined": defined,
                        "top3": [compact(n) for n in rows[:3]],
                    }
                )
            cache = Embeddings(c)
            try:
                v = cache.get_many([case["query"]], "query")[0]
                v = v / np.linalg.norm(v)
                for level in (
                    ("module", "class", "function") if case["level"] == "all" else [case["level"]]
                ):
                    for k in (10, 50):
                        approximate = q.dense(folder, m, v, level, [case["repo"]], k)
                        exact = q.dense(folder, m, v, level, [case["repo"]], k, exact=True)
                        assert len(approximate) == len(exact)
                        comparisons.append(
                            {
                                "case": case["id"],
                                "level": level,
                                "k": k,
                                "recall": len(set(approximate) & set(exact)) / len(exact)
                                if exact
                                else 1,
                            }
                        )
            finally:
                cache.close()
        result["checks"]["code_search_and_filters"] = {
            "status": "passed",
            "queries": len(cases),
            "channel_observations": len(result["observations"]),
        }
        docs = q.search_docs(
            "实例字段 局部准入", repositories=["agentic-trpg"], category="contract", limit=3
        )
        assert docs["results"]
        result["checks"]["document_search"] = {
            "status": "passed",
            "top3": [compact(n) for n in docs["results"]],
        }
        page = q.search_code(
            "ContainerService current_weight",
            repositories=["trpg-state-machine"],
            mode="rrf",
            candidates=50,
            limit=1,
        )
        assert (Path(c["data"]) / "cursor-key.json").exists(), (
            "Read-only validation requires the existing cursor key"
        )
        following = q.search_code(
            "ContainerService current_weight",
            repositories=["trpg-state-machine"],
            mode="rrf",
            candidates=50,
            limit=1,
            cursor=page["next_cursor"],
        )
        assert (
            following["version"] == page["version"]
            and following["results"][0]["node_id"] != page["results"][0]["node_id"]
        )
        result["checks"]["paging"] = {
            "status": "passed",
            "bound_version": page["version"],
            "has_more_is_candidate_pool_only": True,
        }
        nid = page["results"][0]["node_id"]
        node = q.get_nodes([nid], version=page["version"])["nodes"][0]
        assert node["live_file_matches"] and "own_weight" in node["source"]
        result["checks"]["source_location"] = {
            "status": "passed",
            **{
                k: node[k]
                for k in (
                    "node_id",
                    "path",
                    "start",
                    "end",
                    "content_fingerprint",
                    "live_file_matches",
                    "source_origin",
                )
            },
        }
        relations = q.get_relations([nid], ["CALLS"], "out", depth=1, max_edges=30)
        own = [
            e
            for e in relations["edges"]
            if e["target"] and "ContainerService.own_weight#" in e["target"]
        ]
        assert own
        result["checks"]["graph"] = {
            "status": "passed",
            "bounded_relation_examples": own[:2],
            "unresolved_edge_count": m["call_resolution"].get("unresolved"),
            "bounded_static_analysis": m["graph"],
        }
    result["checks"]["hnsw_exact"] = {
        "status": "passed",
        "comparisons": comparisons,
        "mean_recall": float(np.mean([x["recall"] for x in comparisons])),
        "min_recall": min(x["recall"] for x in comparisons),
    }
    result["checks"]["mcp"] = mcp_check(c, output_dir)
    after = {str(p): file_hash(p) for p in protected}
    assert before == after, "Protected real program/config/data changed during validation"
    result["checks"]["protected_data_unchanged"] = {
        "status": "passed",
        "files_hashed": len(before),
        "embedding_api_requests": 0,
    }
    result["checks"]["real_index_update_delete_rename_recovery"] = {
        "status": "not_run",
        "reason": "Forbidden on real data in this source-only task; isolated synthetic/lifecycle tests cover these operations",
    }
    result["checks"]["fresh_embedding_api"] = {
        "status": "not_run",
        "reason": "User forbids new Embedding requests; existing authentic cached vectors used",
    }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = validate(config(args.config), output.parent)
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "passed",
                "source_commit_tested": result["source_commit_tested"],
                "index_version": result["index"]["version"],
                "hnsw": {
                    k: v for k, v in result["checks"]["hnsw_exact"].items() if k != "comparisons"
                },
                "embedding_api_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
