"""Authenticated loopback LCT retrieval/update HTTP MCP, independent of official graph MCP."""

import argparse
import os
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP

from lct.common import load

from .coordinator import Coordinator


def make_server(coordinator):
    server = FastMCP(
        "local-code-tools-cgr",
        host="127.0.0.1",
        port=coordinator.c["retrieval_port"],
        stateless_http=True,
        json_response=True,
        instructions="Use official Neo4j MCP for graph queries. This server provides retrieval and coordinated maintenance updates. Synthetic fixtures do not measure retrieval quality.",
    )

    @server.tool()
    def index_status() -> dict:
        """Report publication state, graph snapshot and index build version without scanning sources."""
        return coordinator.status()

    @server.tool()
    def update_index() -> dict:
        """Close both query entrances, capture configured fixture files, rebuild and validate, then publish."""
        return coordinator.update()

    @server.tool()
    def search_code(
        query: str,
        level: str = "function",
        repositories: list[str] | None = None,
        mode: str = "rrf",
        candidates: int = 50,
        limit: int = 10,
        cursor: str | None = None,
        exact: bool = False,
        include_tests: bool = False,
        expected_version: str | None = None,
    ) -> dict:
        """Existing LCT hierarchy/candidate filters, RRF and bounded signed pagination."""
        return coordinator.call(
            "search_code",
            expected_version,
            query=query,
            level=level,
            repositories=repositories,
            mode=mode,
            candidates=candidates,
            limit=limit,
            cursor=cursor,
            exact=exact,
            include_tests=include_tests,
        )

    @server.tool()
    def search_docs(
        query: str,
        repositories: list[str] | None = None,
        category: str | None = None,
        candidates: int = 50,
        limit: int = 10,
        cursor: str | None = None,
        expected_version: str | None = None,
    ) -> dict:
        """Existing Markdown chapter BM25; no document vectors."""
        return coordinator.call(
            "search_docs",
            expected_version,
            query=query,
            repositories=repositories,
            category=category,
            candidates=candidates,
            limit=limit,
            cursor=cursor,
        )

    @server.tool()
    def get_nodes(
        node_ids: list[str],
        include_source: bool = True,
        version: str | None = None,
        max_bytes: int = 64000,
        expected_version: str | None = None,
    ) -> dict:
        """Canonical captured source and graph mapping, including distinct same-line lambdas."""
        return coordinator.call(
            "get_nodes",
            expected_version,
            node_ids=node_ids,
            include_source=include_source,
            version=version,
            max_bytes=max_bytes,
        )

    return server


class BearerAuth:
    """Authenticate all HTTP routes before the actual MCP app; not an MCP aggregation proxy."""

    def __init__(self, app, token):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        import hmac

        if scope["type"] == "http":
            supplied = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, ("Bearer " + self.token).encode()):
                await send(
                    dict(
                        type="http.response.start",
                        status=401,
                        headers=[(b"www-authenticate", b"Bearer")],
                    )
                )
                await send(dict(type="http.response.body", body=b"Unauthorized"))
                return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    c = load(Path(args.config).resolve())
    token = os.environ.get("LCT_HTTP_TOKEN")
    if not token or len(token) < 24:
        raise ValueError("Set LCT_HTTP_TOKEN to a random 24+ character secret")
    coordinator = Coordinator(c)
    server = make_server(coordinator)
    app = BearerAuth(server.streamable_http_app(), token)
    try:
        uvicorn.run(app, host="127.0.0.1", port=c["retrieval_port"], log_level="warning")
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
