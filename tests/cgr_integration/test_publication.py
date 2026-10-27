"""Owned native Neo4j integration; synthetic vectors, two actual HTTP MCP endpoints."""

import asyncio
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from cgr_adapter.coordinator import Coordinator
from lct.common import ToolError, atomic, load, lock


@pytest.fixture(scope="module")
def integration(tmp_path_factory):
    name = os.environ.get("LCT_NATIVE_TEST_CONFIG")
    if not name:
        pytest.skip("NOT RUN: set LCT_NATIVE_TEST_CONFIG for an explicitly owned native instance")
    base = load(name)
    root = tmp_path_factory.mktemp("cgr-native")
    repo = root / "fixture"
    repo.mkdir()
    (repo / "sample.py").write_bytes((Path(__file__).parent / "fixtures/sample.py").read_bytes())
    (repo / "guide.md").write_text(
        "# Commands\n\nDispatch target command.\n\n## Recovery\n\nRetry a failed publication.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "--", "sample.py", "guide.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Fixture",
        ],
        check=True,
    )
    c = dict(
        base,
        data=str(root / "index"),
        namespace="lct-fixture-" + secrets.token_hex(8),
        repositories=[
            dict(
                name="fixture",
                path=str(repo),
                files=["sample.py"],
                source_roots=["."],
                documents=["guide.md"],
            )
        ],
        official_port=18888,
        retrieval_port=18889,
        synthetic_fixture=True,
    )
    config = root / "config.json"
    atomic(config, c)
    co = Coordinator(c)
    yield co, repo, config
    co.official.stop()
    co.close()


def test_mapping_hierarchy_filters_pagination_rrf_exact_and_source(integration):
    co, _, _ = integration
    out = co.update()
    assert out["state"] == "PUBLISHED" and out["retrieval"]["synthetic_fixture"]
    for level in ["module", "class", "function"]:
        rows = co.call(
            "search_code",
            query="command",
            level=level,
            mode="bm25",
            repositories=["fixture"],
            limit=1,
        )
        assert rows["results"] and {r["kind"] for r in rows["results"]} == {level}
        assert all(r["repository"] == "fixture" for r in rows["results"])
    with pytest.raises(ToolError, match="Unknown repository"):
        co.call("search_code", query="command", repositories=["absent"], mode="rrf")
    first = co.call("search_code", query="command", level="function", mode="bm25", limit=1)
    assert first["has_more"]
    second = co.call(
        "search_code",
        query="command",
        level="function",
        mode="bm25",
        limit=1,
        cursor=first["next_cursor"],
    )
    assert first["results"][0]["node_id"] != second["results"][0]["node_id"]
    dense = co.call("search_code", query="target", level="function", mode="dense", limit=100)
    exact = co.call(
        "search_code", query="target", level="function", mode="dense", exact=True, limit=100
    )
    assert {r["node_id"] for r in dense["results"]} == {r["node_id"] for r in exact["results"]}
    assert co.call("search_code", query="target", mode="rrf")["results"]
    assert co.call("search_docs", query="Recovery")["results"]
    lambdas = co.graph.read(
        'MATCH(n:CGNode {namespace:$ns,kind:"Function"}) WHERE n.name CONTAINS "<lambda>" RETURN n.node_id AS id'
    )
    assert len(lambdas) >= 2 and len({r["id"] for r in lambdas}) == len(lambdas)
    sources = co.call("get_nodes", node_ids=[r["id"] for r in lambdas])["nodes"]
    assert {r["source"] for r in sources} >= {"lambda: target()", "lambda: other()"}
    assert all(r["live_file_matches"] and r["graph_node_id"] == r["node_id"] for r in sources)
    assert all(co.graph.node(out["graph_snapshot"], r["node_id"]) for r in dense["results"])
    with pytest.raises(ToolError, match="Version mismatch"):
        co.call("search_code", "wrong", query="target")


def signature(co):
    import json

    nodes = [
        json.loads(r["payload"])
        for r in co.graph.read("MATCH(n:CGNode {namespace:$ns}) RETURN n.payload AS payload")
    ]
    names = {
        n["node_id"]: (n["path"], n["kind"], n["qualname"], n.get("occurrence")) for n in nodes
    }
    edges = [
        json.loads(r["payload"])
        for r in co.graph.read(
            "MATCH(n:CGNode {namespace:$ns})-[r]->(m:CGNode {namespace:$ns}) RETURN r.payload AS payload"
        )
    ]
    return (
        sorted((n["path"], n["kind"], n["qualname"], n["source_sha256"]) for n in nodes),
        sorted((names[e["source"]], e["kind"], names[e["target"]]) for e in edges),
    )


def test_updates_dirty_bytes_cache_and_full_equivalence(integration):
    co, repo, _ = integration
    first = co.update()
    assert first["retrieval"]["embedding_run"]["new_vectors"] == 0
    assert first["retrieval"]["embedding_run"]["cache_hits"] > 0
    (repo / "extra.py").write_text("def added(): return 9\n", encoding="utf-8")
    co.c["repositories"][0]["files"].append("extra.py")
    added = co.update()
    assert "fixture:extra.py" in added["retrieval"]["incremental"]["added"]
    assert added["source_snapshot"] != first["source_snapshot"]
    (repo / "extra.py").write_text("def added(): return 19\n", encoding="utf-8")
    changed = co.update()
    assert "fixture:extra.py" in changed["retrieval"]["incremental"]["modified"]
    (repo / "extra.py").rename(repo / "renamed.py")
    co.c["repositories"][0]["files"] = ["sample.py", "renamed.py"]
    renamed = co.update()
    assert "fixture:extra.py" in renamed["retrieval"]["incremental"]["deleted"]
    assert not co.graph.read('MATCH(n:CGNode {namespace:$ns,path:"extra.py"}) RETURN n.key')
    (repo / "renamed.py").unlink()
    co.c["repositories"][0]["files"] = ["sample.py"]
    deleted = co.update()
    assert "fixture:renamed.py" in deleted["retrieval"]["incremental"]["deleted"]
    incremental = signature(co)
    atomic(co.data / "last-capture.json", dict(file_hashes={}))
    full = co.update()
    assert signature(co) == incremental
    assert full["retrieval"]["inputs"] == deleted["retrieval"]["inputs"]
    model = co.c["embedding"]["model"]
    co.c["embedding"]["model"] = "SYNTHETIC-ALTERNATE-MODEL"
    alternate = co.update()
    assert alternate["retrieval"]["embedding_run"]["new_vectors"] > 0
    co.c["embedding"]["model"] = model
    old = (repo / "sample.py").read_text(encoding="utf-8")
    (repo / "sample.py").write_text(old.replace("return 1", "return 17"), encoding="utf-8")
    assert co.update()["retrieval"]["embedding_run"]["new_vectors"] > 0


@pytest.mark.parametrize(
    "stage", ["graph", "after_graph", "retrieval", "before_publish", "restart"]
)
def test_failure_restart_refuses_and_retry_recovers(integration, stage):
    co, repo, _ = integration
    if co.state()["state"] != "PUBLISHED":
        co.update()
    old = co.state()["version"]
    (repo / "sample.py").write_text(
        (repo / "sample.py").read_text(encoding="utf-8") + "\n# " + stage + "\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="Injected"):
        co.update(stage)
    assert co.state()["state"] == "FAILED" and co.official.process() is None
    with pytest.raises(ToolError, match="unavailable"):
        co.call("search_code", query="target", mode="bm25")
    restarted = Coordinator(co.c)
    try:
        assert restarted.state()["state"] == "FAILED" and restarted.official.process() is None
        with pytest.raises(ToolError):
            restarted.call("search_docs", query="command")
        assert restarted.update()["version"] != old
    finally:
        restarted.close()


def test_active_retrieval_lock_blocks_writer_before_mutation(integration):
    co, _, _ = integration
    before = co.graph.active()
    with lock(co.data / "publication.lock"):
        with pytest.raises(ToolError):
            co.update()
    assert co.graph.active() == before and co.state()["state"] == "PUBLISHED"


async def tools_and_call(url, auth, callback):
    async with httpx.AsyncClient(auth=auth, timeout=60) as http:
        async with streamable_http_client(url, http_client=http) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                return await callback(session, await session.list_tools())


def decode(result):
    import json

    assert not result.isError, str(result)
    return result.structuredContent or json.loads(result.content[0].text)


def test_actual_independent_mcps_readonly_auth_and_update(integration):
    co, _, config = integration
    atomic(config, co.c)
    auth = load(co.c["auth_file"])
    token = secrets.token_urlsafe(32)
    log = (co.data / "lct-http.log").open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-B", "-m", "cgr_adapter.server", str(config)],
        env=dict(os.environ, LCT_HTTP_TOKEN=token),
        stdout=log,
        stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        for _ in range(300):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", co.c["retrieval_port"])) == 0:
                    break
            if proc.poll() is not None:
                raise AssertionError("LCT HTTP exited; inspect private log")
            time.sleep(0.05)
        url = f"http://127.0.0.1:{co.c['retrieval_port']}/mcp"
        assert httpx.post(url, json={}).status_code == 401
        graph_url = f"http://127.0.0.1:{co.c['official_port']}/mcp"

        async def official(session, tools):
            names = {t.name for t in tools.tools}
            assert {"read-cypher", "get-schema"} <= names and "write-cypher" not in names
            result = await session.call_tool(
                "read-cypher", {"query": "MATCH(n:CGNode) RETURN count(n) AS count"}
            )
            assert not result.isError, str(result)
            rejected = await session.call_tool(
                "read-cypher", {"query": "CREATE (:LCTReadOnlyProbe) RETURN 1 AS n"}
            )
            assert rejected.isError, "Official read-cypher unexpectedly accepted a write"
            assert not co.graph.read("MATCH(n:LCTReadOnlyProbe) RETURN n")
            schema = await session.call_tool("get-schema", {})
            assert not schema.isError, str(schema)
            return dict(
                tools=sorted(names),
                read=[b.text for b in result.content if b.type == "text"],
                schema_ok=True,
            )

        evidence = asyncio.run(
            tools_and_call(graph_url, httpx.BasicAuth(auth["user"], auth["password"]), official)
        )

        class Bearer(httpx.Auth):
            def auth_flow(self, request):
                request.headers["Authorization"] = "Bearer " + token
                yield request

        async def retrieval(session, tools):
            names = {t.name for t in tools.tools}
            assert names == {
                "index_status",
                "update_index",
                "search_code",
                "search_docs",
                "get_nodes",
            }
            assert decode(await session.call_tool("index_status", {}))["state"] == "PUBLISHED"
            result = decode(
                await session.call_tool("search_code", dict(query="target", mode="rrf"))
            )
            nid = result["results"][0]["node_id"]
            assert (
                decode(await session.call_tool("get_nodes", dict(node_ids=[nid])))["nodes"][0][
                    "graph_node_id"
                ]
                == nid
            )
            updated = decode(await session.call_tool("update_index", {}))
            assert updated["state"] == "PUBLISHED"
            bad = await session.call_tool(
                "search_code", dict(query="target", mode="bm25", expected_version="obsolete")
            )
            assert bad.isError
            return dict(
                tools=sorted(names),
                search_version=result["version"],
                update_state=updated["state"],
                version_error=bad.isError,
            )

        evidence["retrieval"] = asyncio.run(tools_and_call(url, Bearer(), retrieval))
        atomic(co.data / "mcp-evidence.json", evidence)
        if os.environ.get("LCT_MCP_EVIDENCE"):
            atomic(os.environ["LCT_MCP_EVIDENCE"], evidence)
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()


def test_old_http_connection_and_inflight_read_drained(integration):
    co, _, _ = integration
    auth = load(co.c["auth_file"])
    url = f"http://127.0.0.1:{co.c['official_port']}/mcp"
    started, ended = Event(), Event()
    failures = []

    def old_connection():
        async def request(session, tools):
            started.set()
            result = await session.call_tool(
                "read-cypher",
                {"query": "UNWIND range(1,20000000) AS x RETURN sum(sqrt(x)) AS total"},
            )
            return result

        try:
            asyncio.run(
                tools_and_call(url, httpx.BasicAuth(auth["user"], auth["password"]), request)
            )
        except BaseException as e:
            failures.append(type(e).__name__)
        finally:
            ended.set()

    thread = Thread(target=old_connection)
    thread.start()
    assert started.wait(15)
    # Wait for an actual database transaction, not just a client start event.
    active = False
    for _ in range(300):
        rows = co.graph.read(
            'SHOW TRANSACTIONS YIELD currentQuery WHERE currentQuery CONTAINS "20000000" AND NOT currentQuery STARTS WITH "SHOW TRANSACTIONS" RETURN currentQuery'
        )
        if rows:
            active = True
            break
        if ended.is_set():
            break
        time.sleep(0.01)
    assert active, "Long read did not overlap; cannot claim inflight isolation"
    co.update()
    thread.join(15)
    assert ended.is_set() and failures
    assert co.state()["state"] == "PUBLISHED"


def test_unowned_data_and_preserved_legacy_path_are_rejected(integration, tmp_path):
    co, _, _ = integration
    target = tmp_path / "unowned"
    target.mkdir()
    (target / "keep.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        Coordinator(dict(co.c, data=str(target)))
    assert (target / "keep.txt").read_text(encoding="utf-8") == "preserve"
    from lct.common import ROOT

    with pytest.raises(ValueError, match="legacy"):
        Coordinator(dict(co.c, data=str(ROOT / "data")))
