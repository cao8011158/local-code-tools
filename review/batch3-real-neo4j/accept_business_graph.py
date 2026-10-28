"""Bounded, read-only-to-source acceptance against the published business SQLite graph.

Run with the owned Neo4j launcher; this never builds sources or calls embeddings.
"""
import asyncio
import collections
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lct.common import ToolError, canonical
from lct.neo4j_graph import Neo4jGraph, load_snapshot, MAX_BATCH_BYTES

CONFIG = Path(__file__).resolve().parents[3] / "batch3-preflight/business-config.json"
DATA = "/tmp/lct-b3-locality-fixed-20261028"
VERSION = "20261028T122745-62019ae507"
NAMESPACE = "batch3-business-20261028"
OUTPUT = ROOT / ".tmp/batch3-real-neo4j" / os.getenv("LCT_BUSINESS_ACCEPTANCE_OUTPUT", "measurements.json")


def check(condition, detail):
    if not condition:
        raise AssertionError(detail)


def main():
    start = time.monotonic()
    c = json.loads(CONFIG.read_text())
    c["data"] = DATA
    evidence = {"namespace": NAMESPACE, "version": VERSION, "checks": [], "seconds": {}}

    def mark(name):
        evidence["checks"].append(name)
        evidence["seconds"][name] = round(time.monotonic() - start, 3)
        print(json.dumps({"check": name, "elapsed": evidence["seconds"][name]}), flush=True)

    try:
        snapshot = load_snapshot(c, VERSION)
        nodes, edges = snapshot["nodes"], snapshot["edges"]
        sites = snapshot["graph"]["sites"]
        check((len(nodes), len(edges), len(sites)) == (5957, 42459, 22416), "business counts")
        check(snapshot["graph"]["analysis_limited"] is True, "analysis limitation lost")
        check(any(s.get("unknown_origin") and s.get("complete") is False for s in sites), "UNKNOWN sites lost")
        check(any(e.get("unknown_origin") and e.get("complete") is False for e in edges), "UNKNOWN edges lost")
        max_record = max(max(len(canonical(n).encode()) for n in nodes),
                         max(len(canonical(e).encode()) for e in edges))
        check(max_record < MAX_BATCH_BYTES, "individual record exceeds 1 MiB")
        evidence["preflight"] = dict(nodes=len(nodes), edges=len(edges), sites=len(sites),
            unknown_sites=sum(bool(s.get("unknown_origin")) for s in sites),
            unknown_edges=sum(bool(e.get("unknown_origin")) for e in edges),
            max_raw_record_bytes=max_record, graph_json_bytes=len(canonical(snapshot["graph"]).encode()),
            fingerprint=snapshot["fingerprint"], analysis_limited=True,
            kinds=dict(collections.Counter(n["kind"] for n in nodes)))
        try:
            load_snapshot(c, "wrong-version")
        except ToolError:
            pass
        else:
            raise AssertionError("load_snapshot accepted missing version")
        mark("sqlite_validated_and_bounds")

        uri = os.environ["LCT_TEST_NEO4J_URI"]
        user = os.environ["LCT_TEST_NEO4J_USER"]
        password = os.environ["LCT_TEST_NEO4J_PASSWORD"]
        database = os.environ["LCT_TEST_NEO4J_DATABASE"]
        by_kind = {kind: next(n for n in nodes if n["kind"] == kind)
                   for kind in ("module", "class", "function")}
        ids = [n["node_id"] for n in by_kind.values()]
        # Select one real CALLS source with UNKNOWN evidence and a manageable closure.
        node_ids = {n["node_id"] for n in nodes}
        calls_counts = collections.Counter(e.get("source") for e in edges if e["kind"] == "CALLS")
        source_id = next(e["source"] for e in edges if e["kind"] == "CALLS" and
                         e.get("unknown_origin") and e.get("source") in node_ids and
                         calls_counts[e["source"]] < 100)
        expected_rel = [e for e in edges if e["kind"] == "CALLS" and e.get("source") == source_id]
        check(any(e.get("unknown_origin") for e in expected_rel), "selected source lacks UNKNOWN")
        evidence["selected"] = {"node_ids": ids, "calls_source": source_id,
                                "calls_count": len(expected_rel)}

        with Neo4jGraph(uri, user, password, database) as graph:
            with graph.driver.session(database=database) as session:
                stale = session.run(
                    "MATCH (x) WHERE x.namespace=$ns AND x.version=$v "
                    "RETURN labels(x) AS labels, count(x) AS c",
                    ns=NAMESPACE, v=VERSION,
                )
                failed_scope_counts = {"/".join(row["labels"]): row["c"] for row in stale}
                check(not failed_scope_counts, f"failed transaction left scope: {failed_scope_counts}")
                evidence["failed_scope_counts"] = dict(snapshot=0, nodes=0, edges=0)
                try:
                    settings = session.run("SHOW SETTINGS YIELD name, value "
                        "WHERE name IN ['server.memory.heap.max_size', "
                        "'dbms.memory.transaction.total.max', 'server.memory.pagecache.size'] "
                        "RETURN name, value")
                    evidence["neo4j_settings"] = {row["name"]: str(row["value"]) for row in settings}
                except Exception as exc:
                    evidence["neo4j_settings_error"] = f"{type(exc).__name__}: {exc}"
            mark("failed_transaction_rollback")
            for ns, v in ((NAMESPACE + "-wrong", VERSION), (NAMESPACE, VERSION + "-wrong")):
                try:
                    graph.snapshot_info(ns, v)
                except ToolError as exc:
                    check("missing" in str(exc), "wrong scope error")
                else:
                    raise AssertionError("wrong scope was visible before import")
            mark("scope_refusal_before_import")
            first = graph.import_snapshot(NAMESPACE, VERSION, snapshot)
            check(first["already_present"] is False, "fresh isolated namespace unexpectedly exists")
            mark("native_import")
            again = graph.import_snapshot(NAMESPACE, VERSION, snapshot)
            check(again["already_present"] is True, "reimport not idempotent")
            mark("idempotent_reimport")
            info = graph.snapshot_info(NAMESPACE, VERSION)
            check(info["fingerprint"] == snapshot["fingerprint"], "fingerprint")
            check((info["nodes"], info["edges"]) == (len(nodes), len(edges)), "projected counts")
            check(info["graph"] == snapshot["graph"], "raw graph/sites mismatch")
            check(info["source"] == snapshot["source"], "source identity mismatch")
            check(graph.get_nodes(NAMESPACE, VERSION, ids) == list(by_kind.values()), "selected raw nodes")
            for kind, node in by_kind.items():
                listed = graph.list_nodes(NAMESPACE, VERSION, kind=kind,
                    repository=node["repository"], limit=5000)["nodes"]
                expected = [n for n in nodes if n["kind"] == kind and
                            n.get("repository") == node["repository"]]
                check(listed == expected, f"{kind} repository filter")
            relations = graph.get_relations(NAMESPACE, VERSION, [source_id], ["CALLS"], "out", 5000)
            check(relations == {"edges": expected_rel, "has_more": False}, "raw CALLS relations")
            mark("selected_sqlite_raw_roundtrip_and_filters")
            native = sum(e.get("source") in node_ids and e.get("target") in node_ids for e in edges)
            with graph.driver.session(database=database) as session:
                counts = session.run("MATCH (s:LCTSnapshot {namespace:$ns, version:$v}) "
                    "RETURN count(s) AS c", ns=NAMESPACE, v=VERSION).single()["c"]
                logical = session.run("MATCH (e:LCTEdge {namespace:$ns, version:$v}) "
                    "RETURN count(e) AS c", ns=NAMESPACE, v=VERSION).single()["c"]
                actual_native = session.run("MATCH ()-[r]->() WHERE r.namespace=$ns AND r.version=$v "
                    "RETURN count(r) AS c", ns=NAMESPACE, v=VERSION).single()["c"]
            check((counts, logical, actual_native) == (1, len(edges), native), "database counts")
            evidence["native_relationships"] = actual_native
            evidence["boundary_logical_edges"] = len(edges) - native
            for ns, v in ((NAMESPACE + "-wrong", VERSION), (NAMESPACE, VERSION + "-wrong")):
                try:
                    graph.get_nodes(ns, v, ids)
                except ToolError as exc:
                    check("missing" in str(exc), "wrong scope read error")
                else:
                    raise AssertionError("wrong scope read succeeded")
            mark("counts_and_wrong_scope_refusal")

        asyncio.run(mcp_check(uri, user, password, database, snapshot, by_kind, source_id, expected_rel))
        mark("loopback_http_mcp")
        evidence["result"] = "PASS"
    except BaseException as exc:
        evidence["result"] = "FAIL"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        evidence["elapsed_seconds"] = round(time.monotonic() - start, 3)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


async def mcp_check(uri, user, password, database, snapshot, by_kind, source_id, expected_rel):
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from lct.neo4j_mcp import create_app

    class Verifier:
        async def verify_token(self, token):
            if token != "local-business-only":
                return None
            return AccessToken(token=token, client_id="local-acceptance",
                expires_at=4102444800, scopes=["graph:read"], resource=resource)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    resource = base + "/mcp"
    settings = AuthSettings(issuer_url="https://issuer.example.invalid",
        resource_server_url=resource, validate_token_resource=True, required_scopes=["graph:read"])
    app = create_app(uri=uri, user=user, password=password, database=database,
        namespace=NAMESPACE, version=VERSION, token_verifier=Verifier(), auth=settings,
        allowed_host=f"127.0.0.1:{port}", allowed_origin=base)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.05)
        check(server.started, "MCP server startup")
        async with httpx.AsyncClient() as client:
            response = await client.post(resource, json={})
            check(response.status_code == 401, "unauthenticated MCP request")
        async with streamablehttp_client(resource, headers={
            "Authorization": "Bearer local-business-only", "Origin": base,
        }) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                check({t.name for t in tools.tools} ==
                      {"graph_status", "list_nodes", "get_nodes", "get_relations"}, "MCP tool set")
                check(all(t.annotations.readOnlyHint for t in tools.tools), "MCP read-only hints")

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    check(not result.isError, f"MCP {name}: {result.content}")
                    payload = result.structuredContent
                    if payload is None:
                        payload = json.loads(next(c.text for c in result.content if c.type == "text"))
                    check((payload["namespace"], payload["version"], payload["fingerprint"]) ==
                          (NAMESPACE, VERSION, snapshot["fingerprint"]), "MCP scope")
                    return payload["data"]

                status = await call("graph_status", {})
                check((status["nodes"], status["edges"]) ==
                      (len(snapshot["nodes"]), len(snapshot["edges"])), "MCP graph counts")
                check(status["graph"] == snapshot["graph"] and
                      status["source"] == snapshot["source"], "MCP sites/source evidence")
                check(status["graph"]["analysis_limited"] is True and
                      any(s.get("unknown_origin") for s in status["graph"]["sites"]),
                      "MCP UNKNOWN/limited evidence")
                for kind, node in by_kind.items():
                    listed = await call("list_nodes", {"kind": kind,
                        "repository": node["repository"], "limit": 1})
                    check(listed["nodes"][0]["kind"] == kind, "MCP filter")
                selected = await call("get_nodes", {"ids": [n["node_id"] for n in by_kind.values()]})
                check(selected == list(by_kind.values()), "MCP selected raw nodes")
                rel = await call("get_relations", {"ids": [source_id], "types": ["CALLS"],
                    "direction": "out", "limit": 5000})
                check(rel == {"edges": expected_rel, "has_more": False}, "MCP raw relations")
                wrong = await session.call_tool("get_nodes", {"ids": [source_id],
                    "namespace": "wrong", "version": "wrong"})
                if not wrong.isError:
                    payload = wrong.structuredContent or json.loads(next(
                        c.text for c in wrong.content if c.type == "text"))
                    check(payload["namespace"] == NAMESPACE and payload["version"] == VERSION,
                          "MCP caller changed scope")
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)


if __name__ == "__main__":
    main()
