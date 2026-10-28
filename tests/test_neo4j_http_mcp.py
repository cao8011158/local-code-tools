"""Real loopback HTTP MCP and owned Neo4j acceptance for the small fixture."""

import asyncio
import json
import os
import socket
import subprocess
import sys

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from lct.neo4j_graph import Neo4jGraph, load_snapshot
from lct.neo4j_mcp import create_app
from tests.test_small_graph_mcp_e2e import ROOT, prepare


class LocalTestVerifier:
    """Synthetic test credentials only; never use as a production verifier."""

    def __init__(self, resource):
        self.resource = resource

    async def verify_token(self, token):
        if token not in ("local-full", "local-no-scope", "local-wrong-audience"):
            return None
        return AccessToken(
            token=token, client_id="local-test", expires_at=4102444800,
            scopes=["graph:read"] if token != "local-no-scope" else [],
            resource=self.resource if token != "local-wrong-audience" else "https://other.invalid/mcp",
        )


def settings(resource="http://127.0.0.1:8765/mcp", scopes=None):
    return AuthSettings(issuer_url="https://issuer.example.invalid",
                        resource_server_url=resource, validate_token_resource=True,
                        required_scopes=["graph:read"] if scopes is None else scopes)


def test_factory_requires_external_auth():
    kw = dict(uri="bolt://127.0.0.1:7687", user="neo4j", password="x",
              database="neo4j", namespace="test", version="v",
              allowed_host="127.0.0.1:8765", allowed_origin="http://127.0.0.1:8765")
    with pytest.raises(ValueError, match="verifier"):
        create_app(**kw, token_verifier=None, auth=settings())
    with pytest.raises(ValueError, match="scope"):
        create_app(**kw, token_verifier=LocalTestVerifier("x"), auth=settings(scopes=[]))
    with pytest.raises(ValueError, match="Exact"):
        create_app(**(kw | {"allowed_host": "*.example.com"}),
                   token_verifier=LocalTestVerifier("x"), auth=settings())


def test_real_http_mcp_read_only(tmp_path, monkeypatch):
    uri = os.getenv("LCT_TEST_NEO4J_URI")
    if not uri:
        pytest.skip("LCT_TEST_NEO4J_URI not set; real Neo4j service required")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    for proxy_name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                       "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(proxy_name, raising=False)
    _, config_path, env = prepare(tmp_path)
    built = subprocess.run(
        [sys.executable, str(ROOT / "local_code_tools.py"), "--config", str(config_path),
         "build", "--offline", "--lexical-only"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=90,
    )
    assert built.returncode == 0, built.stderr
    version = json.loads(built.stdout)["version"]
    snapshot = load_snapshot(json.loads(config_path.read_text()), version)
    nodes, edges = snapshot["nodes"], snapshot["edges"]
    assert (len(nodes), len(edges)) == (17, 30)
    namespace = "http-" + tmp_path.name
    user = os.getenv("LCT_TEST_NEO4J_USER", "neo4j")
    password = os.getenv("LCT_TEST_NEO4J_PASSWORD", "synthetic-lct-batch1-only")
    database = os.getenv("LCT_TEST_NEO4J_DATABASE", "neo4j")
    with Neo4jGraph(uri, user, password, database) as graph:
        graph.import_snapshot(namespace, version, snapshot)

    async def exercise():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        resource = base + "/mcp"
        app = create_app(uri=uri, user=user, password=password, database=database,
                         namespace=namespace, version=version,
                         token_verifier=LocalTestVerifier(resource), auth=settings(resource),
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
                await asyncio.sleep(0.05)
            assert server.started
            async with httpx.AsyncClient() as client:
                for token, code in ((None, 401), ("wrong", 401),
                                    ("local-wrong-audience", 401), ("local-no-scope", 403)):
                    headers = {"Authorization": f"Bearer {token}"} if token else {}
                    response = await client.post(resource, headers=headers, json={})
                    assert response.status_code == code, response.text
                headers = {"Authorization": "Bearer local-full", "Origin": "https://evil.invalid"}
                assert (await client.post(resource, headers=headers, json={})).status_code == 403
                headers = {"Authorization": "Bearer local-full", "Host": "evil.invalid"}
                assert (await client.post(resource, headers=headers, json={})).status_code == 421

            async with streamablehttp_client(resource, headers={
                "Authorization": "Bearer local-full", "Origin": base,
            }) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} == {
                        "graph_status", "list_nodes", "get_nodes", "get_relations"}
                    for tool in tools.tools:
                        assert "namespace" not in tool.inputSchema.get("properties", {})
                        assert "version" not in tool.inputSchema.get("properties", {})
                        assert tool.annotations.readOnlyHint is True
                        assert tool.annotations.destructiveHint is False
                        assert tool.annotations.idempotentHint is True
                        assert tool.annotations.openWorldHint is False

                    async def call(name, args=None):
                        result = await session.call_tool(name, args or {})
                        assert not result.isError, result.content
                        payload = result.structuredContent
                        if payload is None:
                            payload = json.loads(next(c.text for c in result.content if c.type == "text"))
                        assert (payload["namespace"], payload["version"], payload["fingerprint"]) == (
                            namespace, version, snapshot["fingerprint"])
                        return payload["data"]

                    status = await call("graph_status")
                    assert (status["nodes"], status["edges"]) == (17, 30)
                    assert status["graph"] == snapshot["graph"]
                    for kind in ("module", "class", "function", "documentsection"):
                        listed = await call("list_nodes", {"kind": kind, "limit": 500})
                        assert listed["nodes"] == [n for n in nodes if n["kind"] == kind]
                    assert (await call("list_nodes", {"limit": 1}))["has_more"]
                    assert await call("get_nodes", {"ids": [n["node_id"] for n in nodes]}) == nodes
                    caller = next(n for n in nodes if n["qualname"] == "caller")
                    relations = await call("get_relations", {
                        "ids": [caller["node_id"]], "types": ["CALLS"], "direction": "out"})
                    expected = [e for e in edges if e["kind"] == "CALLS" and
                                e["source"] == caller["node_id"]]
                    assert relations["edges"] == expected
                    assert any(e["unknown_origin"] and not e["complete"] for e in expected)
                    assert await call("get_nodes", {"ids": ["nonexistent"]}) == []
                    bad = await session.call_tool("get_nodes", {
                        "ids": [caller["node_id"]], "namespace": "other", "version": "other"})
                    if not bad.isError:
                        payload = bad.structuredContent or json.loads(
                            next(c.text for c in bad.content if c.type == "text"))
                        assert payload["namespace"] == namespace
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=15)

    asyncio.run(exercise())
    with Neo4jGraph(uri, user, password, database) as graph:
        assert graph.snapshot_info(namespace, version)["fingerprint"] == snapshot["fingerprint"]
        assert graph.list_nodes(namespace, version, limit=500)["nodes"] == nodes
