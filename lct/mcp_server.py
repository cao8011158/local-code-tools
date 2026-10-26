"""Read-only local stdio MCP. Protocol stdout is owned by the official MCP SDK."""

from mcp.server.fastmcp import FastMCP

from .common import config
from .query import Query

server = FastMCP(
    "agentic-trpg-local-code",
    log_level="WARNING",
    instructions="Search source/docstrings by repository and hierarchy; inspect version/freshness, then get_nodes and conservative graph relations. Status refresh explicitly scans source. Historical evidence is not current authority.",
)
core = Query(config())


@server.tool()
def index_status(refresh: bool = False) -> dict:
    """Report index compatibility/counts and last freshness check; refresh scans included files."""
    return core.index_status(refresh)


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
) -> dict:
    """Search module/class/function/all using dense, bm25 or rrf. All interleaves levels. Candidate cap 1000; has_more covers only that pool. Pass identical query conditions with next_cursor. Exact selects cosine baseline. Tests excluded by default."""
    return core.search_code(
        query, level, repositories, mode, candidates, limit, cursor, exact, include_tests
    )


@server.tool()
def search_docs(
    query: str,
    repositories: list[str] | None = None,
    category: str | None = None,
    candidates: int = 50,
    limit: int = 10,
    cursor: str | None = None,
) -> dict:
    """BM25 Markdown sections. Category: contract, implementation, history, experiment; no DOC vectors."""
    return core.search_docs(query, repositories, category, candidates, limit, cursor)


@server.tool()
def get_nodes(
    node_ids: list[str],
    include_source: bool = True,
    version: str | None = None,
    max_bytes: int = 64000,
) -> dict:
    """Batch exact nodes from fixed index; source is indexed snapshot. live_file_matches verifies bytes, never blindly applies old lines to changed files. Cap 50 nodes/200000 source bytes."""
    return core.get_nodes(node_ids, include_source, version, max_bytes)


@server.tool()
def get_relations(
    node_ids: list[str],
    relation_types: list[str] | None = None,
    direction: str = "out",
    depth: int = 1,
    max_nodes: int = 100,
    max_edges: int = 200,
    max_bytes: int = 100000,
    version: str | None = None,
) -> dict:
    """Bounded CONTAINS/IMPORTS/CALLS/INHERITS traversal. Incoming CALLS finds callers; outgoing finds callees; incoming CONTAINS finds owner. Preserve possible/unresolved/boundary evidence."""
    return core.get_relations(
        node_ids, relation_types, direction, depth, max_nodes, max_edges, max_bytes, version
    )


def main():
    """Start stdio only; API cache/build logging goes to stderr."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
