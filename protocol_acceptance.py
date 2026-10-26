"""Bounded real stdio JSON-RPC MCP smoke, with per-message timeout and protocol-only stdout."""

import json
import queue
import subprocess
import sys
import threading

from lct.common import ROOT, atomic


def main():
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "local_code_tools.py"), "mcp"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    outq = queue.Queue()
    errors = []

    def reader():
        for line in process.stdout:
            try:
                value = json.loads(line)
                print(
                    "MCP received id="
                    + str(value.get("id"))
                    + " method="
                    + str(value.get("method")),
                    file=sys.stderr,
                    flush=True,
                )
                outq.put(value)
            except ValueError:
                outq.put({"invalid_stdout": line[:200]})

    def errreader():
        for line in process.stderr:
            errors.append(line[:500])
            with (ROOT / "reports/mcp-diagnostic.log").open("a", encoding="utf-8") as diagnostic:
                diagnostic.write(line)

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=errreader, daemon=True).start()
    sequence = 0
    results = {"calls": []}

    def send(method, params=None, notification=False):
        nonlocal sequence
        sequence += 1
        request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            request["id"] = sequence
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        if notification:
            return None
        while True:
            try:
                value = outq.get(timeout=30)
            except queue.Empty:
                raise RuntimeError(
                    "MCP timeout at " + method + " stderr=" + "".join(errors[-3:])
                ) from None
            if "invalid_stdout" in value:
                raise RuntimeError("Nonprotocol stdout: " + value["invalid_stdout"])
            if value.get("id") == sequence:
                if "error" in value:
                    raise RuntimeError(str(value["error"]))
                return value["result"]

    def call(name, args):
        print("MCP call " + name, file=sys.stderr, flush=True)
        result = send("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            raise RuntimeError("MCP tool error: " + name + " " + str(result.get("content")))
        value = result.get("structuredContent")
        if value is None:
            value = json.loads(next(x["text"] for x in result["content"] if x["type"] == "text"))
        results["calls"].append({"tool": name, "ok": True})
        atomic(ROOT / "reports/mcp-progress.json", results)
        return value

    try:
        init = send(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "local-code-acceptance", "version": "1.0"},
            },
        )
        send("notifications/initialized", notification=True)
        listed = send("tools/list")
        results["server"] = init["serverInfo"]
        results["tools"] = [x["name"] for x in listed["tools"]]
        assert set(results["tools"]) == {
            "index_status",
            "search_code",
            "search_docs",
            "get_nodes",
            "get_relations",
        }
        status = call("index_status", {"refresh": True})
        assert status["status"] in ("ready", "ready_without_dense"), status
        code = call(
            "search_code",
            {
                "query": "ContainerService",
                "level": "class",
                "mode": "bm25",
                "repositories": ["trpg-state-machine"],
                "limit": 3,
            },
        )
        assert code["results"]
        docs = call(
            "search_docs", {"query": "SQLite COMMIT RAM 发布", "category": "contract", "limit": 3}
        )
        assert docs["results"]
        functions = call(
            "search_code",
            {
                "query": "ContainerService weight",
                "mode": "bm25",
                "repositories": ["trpg-state-machine"],
                "limit": 3,
            },
        )
        nid = functions["results"][0]["node_id"]
        nodes = call("get_nodes", {"node_ids": [nid], "version": functions["version"]})
        assert nodes["nodes"][0]["live_file_matches"]
        rels = call(
            "get_relations",
            {
                "node_ids": [nid],
                "relation_types": ["CONTAINS", "CALLS"],
                "direction": "both",
                "depth": 1,
                "max_edges": 20,
            },
        )
        if status.get("dense_ready"):
            for level, query in [
                ("module", "world_containers ContainerService weights"),
                ("class", "ContainerService"),
                ("function", "ContainerService current_weight"),
            ]:
                for mode in ("dense", "rrf"):
                    dense_result = call(
                        "search_code",
                        {
                            "query": query,
                            "level": level,
                            "repositories": ["trpg-state-machine"],
                            "mode": mode,
                            "limit": 3,
                        },
                    )
                    assert dense_result["results"] and all(
                        n["kind"] == level for n in dense_result["results"]
                    )
            results["dense_and_rrf_three_levels"] = True
        results.update(
            version=status["version"],
            dense_ready=status.get("dense_ready"),
            code_top=code["results"],
            doc_top=docs["results"],
            source_verified=True,
            relation_edges=len(rels["edges"]),
            stdout="valid JSON-RPC lines only",
        )
        atomic(ROOT / "reports/mcp-protocol.json", results)
        print(
            json.dumps(
                {k: v for k, v in results.items() if k not in ("code_top", "doc_top")},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()


if __name__ == "__main__":
    main()
