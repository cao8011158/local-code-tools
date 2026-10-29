"""Accept a published business SQLite graph against an owned, bounded Neo4j service.

Run with an externally enforced 540-second timeout and 1 GiB owned Neo4j memory.
Only a local test token and loopback HTTP are used; no extraction or API calls.
"""
import argparse
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
from lct.common import config
from lct.storage import current, manifest
from lct.neo4j_graph import Neo4jGraph, load_snapshot, MAX_BATCH_BYTES
import lct.neo4j_graph as projection

FROZEN_HEADS = {
    "agentic-trpg": "ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436",
    "trpg-state-machine": "4166e52f0809ae80ba1694295bb0739acec76bd8",
    "trpg-rules-engine": "ab276fffc5ff02a973e1c767543e712dd0897451",
}


def check(condition, detail):
    if not condition:
        raise AssertionError(detail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Published business index config")
    parser.add_argument("--version", help="Published version; defaults to current.json")
    parser.add_argument("--namespace", required=True, help="Fresh unique acceptance namespace")
    parser.add_argument("--output", required=True, type=Path, help="Small JSON evidence report")
    args = parser.parse_args()
    namespace = args.namespace
    output = args.output
    start = time.monotonic()
    evidence = {"namespace": namespace, "version": args.version, "checks": [], "seconds": {},
                "certification": "limited: UNKNOWN evidence and analysis_limited remain"}
    stage_start = start

    def mark(name):
        nonlocal stage_start
        now = time.monotonic()
        evidence["checks"].append(name)
        evidence["seconds"][name] = round(now - stage_start, 3)
        stage_start = now
        print(json.dumps({"check": name, "stage_seconds": evidence["seconds"][name],
                          "elapsed": round(now - start, 3)}), flush=True)

    try:
        c = config(args.config)
        version = args.version or current(c)
        check(version is not None, "published current version missing")
        evidence["version"] = version
        _, m = manifest(c, version)
        source_heads = {r["name"]: r["head"] for r in m["repositories"]}
        check(source_heads == FROZEN_HEADS, f"frozen business source heads mismatch: {source_heads}")
        snapshot = load_snapshot(c, version)
        nodes, edges = snapshot["nodes"], snapshot["edges"]
        sites = snapshot["graph"]["sites"]
        check((len(nodes), len(edges), len(sites)) ==
              (m["node_count"], sum(m["edges"].values()), len(m["graph"]["sites"])),
              "published manifest counts")
        check(snapshot["source"]["repositories"] == m["repositories"], "source repository identity")
        check(snapshot["graph"]["analysis_limited"] is True, "analysis limitation lost")
        check(any(s.get("unknown_origin") and s.get("complete") is False for s in sites), "UNKNOWN sites lost")
        check(any(e.get("unknown_origin") and e.get("complete") is False for e in edges), "UNKNOWN edges lost")
        max_record = max(max(len(canonical(n).encode()) for n in nodes),
                         max(len(canonical(e).encode()) for e in edges))
        check(max_record < MAX_BATCH_BYTES, "individual record exceeds 1 MiB")
        evidence["preflight"] = dict(nodes=len(nodes), edges=len(edges), sites=len(sites),
            files=len(m["files"]), manifest_edges=m["edges"],
            unknown_sites=sum(bool(s.get("unknown_origin")) for s in sites),
            unknown_edges=sum(bool(e.get("unknown_origin")) for e in edges),
            max_raw_record_bytes=max_record, graph_json_bytes=len(canonical(snapshot["graph"]).encode()),
            fingerprint=snapshot["fingerprint"], analysis_limited=True, source_heads=source_heads,
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
        expected_rel = sorted((e for e in edges if e["kind"] == "CALLS" and
                               e.get("source") == source_id), key=lambda e: e["edge_id"])
        check(any(e.get("unknown_origin") for e in expected_rel), "selected source lacks UNKNOWN")
        evidence["selected"] = {"node_ids": ids, "calls_source": source_id,
                                "calls_count": len(expected_rel)}

        with Neo4jGraph(uri, user, password, database) as graph:
            with graph.driver.session(database=database) as session:
                stale = session.run("MATCH (x {namespace:$ns, version:$v}) RETURN count(x) AS c",
                                    ns=namespace, v=version).single()["c"]
                check(stale == 0, "namespace must be unique and empty before import")
                try:
                    settings = session.run("SHOW SETTINGS YIELD name, value "
                        "WHERE name IN ['server.memory.heap.max_size', "
                        "'dbms.memory.transaction.total.max', 'server.memory.pagecache.size'] "
                        "RETURN name, value")
                    evidence["neo4j_settings"] = {row["name"]: str(row["value"]) for row in settings}
                except Exception as exc:
                    evidence["neo4j_settings_error"] = f"{type(exc).__name__}: {exc}"
            mark("fresh_namespace")
            for ns, v in ((namespace + "-wrong", version), (namespace, version + "-wrong")):
                try:
                    graph.snapshot_info(ns, v)
                except ToolError as exc:
                    check("missing" in str(exc), "wrong scope error")
                else:
                    raise AssertionError("wrong scope was visible before import")
            mark("scope_refusal_before_import")
            batch_stats = {"count": 0, "max_records": 0, "max_bytes": 0, "stages": {}}
            original_write = projection._write

            def measured_write(session, scope, owner, query, rows=None):
                if rows is not None:
                    size = sum(len(canonical(row).encode("utf-8")) for row in rows)
                    check(len(rows) <= projection.MAX_BATCH_RECORDS and size <= MAX_BATCH_BYTES,
                          "actual import batch bound")
                    batch_stats["count"] += 1
                    batch_stats["max_records"] = max(batch_stats["max_records"], len(rows))
                    batch_stats["max_bytes"] = max(batch_stats["max_bytes"], size)
                    stage = ("node" if "CREATE (n:LCTNode:" in query else
                             "edge" if "CREATE (e:LCTEdge" in query else
                             "chunk" if "CREATE (c:LCTChunk" in query else "native_relation")
                    batch_stats["stages"][stage] = batch_stats["stages"].get(stage, 0) + 1
                return original_write(session, scope, owner, query, rows)

            projection._write = measured_write
            try:
                first = graph.import_snapshot(namespace, version, snapshot)
            finally:
                projection._write = original_write
            evidence["batches"] = batch_stats
            check(first["already_present"] is False, "fresh isolated namespace unexpectedly exists")
            check(batch_stats["count"] > 0 and all(batch_stats["stages"].get(k, 0) > 0
                                                   for k in ("node", "edge", "chunk", "native_relation")),
                  "actual import batch stages")
            mark("native_import")
            again = graph.import_snapshot(namespace, version, snapshot)
            check(again["already_present"] is True, "reimport not idempotent")
            mark("idempotent_reimport")
            info = graph.snapshot_info(namespace, version)
            check(info["fingerprint"] == snapshot["fingerprint"], "fingerprint")
            check((info["nodes"], info["edges"]) == (len(nodes), len(edges)), "projected counts")
            check(info["graph"] == snapshot["graph"], "raw graph/sites mismatch")
            check(info["source"] == snapshot["source"], "source identity mismatch")
            check(graph.get_nodes(namespace, version, ids) == list(by_kind.values()), "selected raw nodes")
            for kind, node in by_kind.items():
                listing = graph.list_nodes(namespace, version, kind=kind,
                    repository=node["repository"], limit=5000)
                expected = [n for n in nodes if n["kind"] == kind and
                            n.get("repository") == node["repository"]]
                check(listing == {"nodes": expected, "has_more": False},
                      f"{kind} repository filter")
            relations = graph.get_relations(namespace, version, [source_id], ["CALLS"], "out", 5000)
            check(relations == {"edges": expected_rel, "has_more": False}, "raw CALLS relations")
            mark("metadata_roundtrip_and_filters")
            native = sum(e.get("source") in node_ids and e.get("target") in node_ids for e in edges)
            with graph.driver.session(database=database) as session:
                marker = session.run("MATCH (s:LCTSnapshot {namespace:$ns, version:$v}) "
                    "RETURN s.complete AS complete, s.state AS state, s.node_count AS nodes, "
                    "s.edge_count AS edges, s.native_count AS native, count(s) AS c",
                    ns=namespace, v=version).single()
                counts = marker["c"]
                check(marker["complete"] is True and marker["state"] == "complete", "publication marker")
                check((marker["nodes"], marker["edges"], marker["native"]) ==
                      (len(nodes), len(edges), native), "publication counts")
                logical = session.run("MATCH (e:LCTEdge {namespace:$ns, version:$v}) "
                    "RETURN count(e) AS c", ns=namespace, v=version).single()["c"]
                actual_nodes = session.run("MATCH (n:LCTNode {namespace:$ns, version:$v}) "
                    "RETURN count(n) AS c", ns=namespace, v=version).single()["c"]
                actual_native = session.run("MATCH ()-[r]->() WHERE r.namespace=$ns AND r.version=$v "
                    "RETURN count(r) AS c", ns=namespace, v=version).single()["c"]
                check(actual_nodes == len(nodes), "native node count")

                def exact_rows(query, expected, label):
                    stream = session.run(query, ns=namespace, v=version)
                    for want in expected:
                        got = stream.peek()
                        check(got is not None, f"{label} missing")
                        row = next(stream)
                        check(row["id"] == want["node_id" if label == "node" else "edge_id"] and
                              row["raw"] == canonical(want), f"{label} raw mismatch")
                    check(stream.peek() is None, f"{label} extra")

                exact_rows("MATCH (n:LCTNode {namespace:$ns, version:$v}) "
                           "RETURN n.node_id AS id, n.raw_json AS raw ORDER BY id", nodes, "node")
                exact_rows("MATCH (e:LCTEdge {namespace:$ns, version:$v}) "
                           "RETURN e.edge_id AS id, e.raw_json AS raw ORDER BY id", edges, "edge")
                native_expected = sorted((e for e in edges if e.get("source") in node_ids and
                                          e.get("target") in node_ids), key=lambda e: e["edge_id"])
                rows = session.run("MATCH (a:LCTNode {namespace:$ns, version:$v})-[r]->"
                                   "(b:LCTNode {namespace:$ns, version:$v}) "
                                   "RETURN r.edge_id AS id, type(r) AS kind, a.node_id AS source, "
                                   "b.node_id AS target ORDER BY id", ns=namespace, v=version)
                for want in native_expected:
                    check(rows.peek() is not None, "native relation missing")
                    got = next(rows)
                    check((got["id"], got["kind"], got["source"], got["target"]) ==
                          (want["edge_id"], want["kind"], want["source"], want["target"]),
                          "native relation mismatch")
                check(rows.peek() is None, "extra native relation")
            check((counts, logical, actual_native) == (1, len(edges), native), "database counts")
            evidence["native_relationships"] = actual_native
            evidence["boundary_logical_edges"] = len(edges) - native
            mark("exact_full_database_roundtrip_and_publication")
            for ns, v in ((namespace + "-wrong", version), (namespace, version + "-wrong")):
                try:
                    graph.get_nodes(ns, v, ids)
                except ToolError as exc:
                    check("missing" in str(exc), "wrong scope read error")
                else:
                    raise AssertionError("wrong scope read succeeded")
            mark("counts_and_wrong_scope_refusal")

        asyncio.run(mcp_check(uri, user, password, database, namespace, version,
                              snapshot, by_kind, source_id, expected_rel))
        mark("loopback_http_mcp")
        evidence["result"] = "PASS"
    except BaseException as exc:
        evidence["result"] = "FAIL"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        evidence["elapsed_seconds"] = round(time.monotonic() - start, 3)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


async def mcp_check(uri, user, password, database, namespace, version,
                    snapshot, by_kind, source_id, expected_rel):
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from lct.neo4j_mcp import create_app
    from unittest.mock import patch

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
    original_info = Neo4jGraph.snapshot_info
    info_calls = []

    def counted_info(graph, ns, v):
        info_calls.append((ns, v))
        return original_info(graph, ns, v)

    # The HTTP app must initialize from the small fingerprint marker alone.
    spy = patch.object(Neo4jGraph, "snapshot_info", counted_info)
    spy.start()
    app = create_app(uri=uri, user=user, password=password, database=database,
        namespace=namespace, version=version, token_verifier=Verifier(), auth=settings,
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
        check(not info_calls, "MCP startup hydrated full status before graph_status")
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
                    check(not result.isError, f"MCP {name} returned an error")
                    payload = result.structuredContent
                    if payload is None:
                        payload = json.loads(next(c.text for c in result.content if c.type == "text"))
                    check((payload["namespace"], payload["version"], payload["fingerprint"]) ==
                          (namespace, version, snapshot["fingerprint"]), "MCP scope")
                    return payload["data"]

                status = await call("graph_status", {})
                check(info_calls == [(namespace, version)], "graph_status hydration count")
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
                    check(payload["namespace"] == namespace and payload["version"] == version,
                          "MCP caller changed scope")
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=15)
        finally:
            spy.stop()


if __name__ == "__main__":
    main()
