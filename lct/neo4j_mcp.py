"""Authenticated, read-only Streamable HTTP view of one complete Neo4j snapshot.

The embedding application supplies an OAuth token verifier and issuer settings.
There is intentionally no standalone unauthenticated server command.
"""

from contextlib import asynccontextmanager

import anyio
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .neo4j_graph import Neo4jGraph, _scope


def create_app(*, uri: str, user: str, password: str, database: str,
               namespace: str, version: str, token_verifier: TokenVerifier,
               auth: AuthSettings, allowed_host: str, allowed_origin: str):
    """Build an ASGI app scoped to exactly one imported snapshot.

    ``token_verifier`` must verify issuer, signature, expiry, and intended audience;
    the SDK additionally checks its resource and the required graph:read scope.
    Host includes the serving port (e.g. ``127.0.0.1:8765``).
    """
    _scope(namespace, version)
    if token_verifier is None or not callable(getattr(token_verifier, "verify_token", None)):
        raise ValueError("An external OAuth token verifier is required")
    if not isinstance(auth, AuthSettings) or not auth.issuer_url or not auth.resource_server_url:
        raise ValueError("Issuer and resource server auth settings are required")
    if not auth.validate_token_resource or "graph:read" not in (auth.required_scopes or []):
        raise ValueError("Resource validation and graph:read scope are required")
    if not all(isinstance(x, str) and x and "*" not in x for x in (allowed_host, allowed_origin)):
        raise ValueError("Exact allowed Host and Origin are required")

    graph = None
    fingerprint = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal graph, fingerprint
        try:
            graph = await anyio.to_thread.run_sync(Neo4jGraph, uri, user, password, database)
            info = await anyio.to_thread.run_sync(graph.snapshot_info, namespace, version)
            fingerprint = info["fingerprint"]
        except Exception:
            if graph is not None:
                await anyio.to_thread.run_sync(graph.close)
            raise RuntimeError("Graph snapshot unavailable") from None
        try:
            async with sdk_lifespan(app):
                yield
        finally:
            await anyio.to_thread.run_sync(graph.close)
            graph = None

    server = FastMCP(
        "lct-neo4j-readonly", token_verifier=token_verifier, auth=auth,
        instructions=("Read-only view of one fixed namespace and version. "
                      "UNKNOWN or partial graph evidence is not a resolved call."),
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[allowed_host], allowed_origins=[allowed_origin],
        ),
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False)

    async def read(method, *args):
        try:
            data = await anyio.to_thread.run_sync(method, namespace, version, *args)
            return dict(namespace=namespace, version=version, fingerprint=fingerprint, data=data)
        except Exception:
            raise RuntimeError("Graph read unavailable") from None

    @server.tool(annotations=read_only)
    async def graph_status() -> dict:
        """Get counts, source identity and unresolved graph sites for this snapshot."""
        return await read(graph.snapshot_info)

    @server.tool(annotations=read_only)
    async def list_nodes(kind: str | None = None, repository: str | None = None,
                         limit: int = 100) -> dict:
        """List bounded nodes by kind and repository."""
        return await read(graph.list_nodes, kind, repository, limit)

    @server.tool(annotations=read_only)
    async def get_nodes(ids: list[str]) -> dict:
        """Get nodes in requested ID order, omitting unknown IDs."""
        return await read(graph.get_nodes, ids)

    @server.tool(annotations=read_only)
    async def get_relations(ids: list[str], types: list[str] | None = None,
                            direction: str = "both", limit: int = 100) -> dict:
        """Get bounded incoming and/or outgoing relationships for node IDs."""
        return await read(graph.get_relations, ids, types, direction, limit)

    app = server.streamable_http_app()
    sdk_lifespan = app.router.lifespan_context
    app.router.lifespan_context = lifespan
    return app
