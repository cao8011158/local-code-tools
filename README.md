# Agentic TRPG Local Code Tools

Local Code Tools (LCT) uses pinned Code-Graph-RAG 0.6.30 for the code graph, Python analysis and vector search. LCT owns a small SQLite BM25 index for code and Markdown, combines BM25 with CGR vector results, and exposes a companion MCP search server. This checkout contains no project indexes, vectors or model weights.

## Install and configure

Requires Python 3.12, Git and uv. From this checkout:

```powershell
uv sync --locked
```

Edit [configs/agentic-trpg.toml](configs/agentic-trpg.toml) for your sibling repository layout. Its index and model cache paths resolve relative to the TOML file and default to this checkout's ignored `.local/` directory. A local Qdrant HTTP service must be available at the configured loopback address. You can optionally configure a downloaded Qdrant executable and data directory so `lct up` starts it when needed. See [CGR local retrieval](docs/CGR_LOCAL_RETRIEVAL.md) for setup and data-flow details.

```powershell
uv run --locked lct up --config configs/agentic-trpg.toml
uv run --locked lct refresh --config configs/agentic-trpg.toml --project SM
uv run --locked lct hybrid-search --config configs/agentic-trpg.toml --project trpg-state-machine "SessionMemory publication"
uv run --locked lct doc-search --config configs/agentic-trpg.toml "runtime contract"
```

`up` downloads public UniXcoder assets when absent, builds missing indexes through CGR, and registers two MCP servers in the current Codex config. It can run for a long time and changes local runtime state. Run it only when ready to create or refresh that data. `refresh` explicitly updates one configured project; searches use published data. No hosted embedding API is needed.

## MCP and ownership

- `lct_graph` delegates to CGR's read-only workspace MCP. Its allowlist is `resolve`, `definition`, `context`, `callers`, `callees`, `list_projects`.
- `lct_search` exposes LCT's `hybrid_search`, `search_docs` and `refresh_index`. The first two read published indexes; `refresh_index` explicitly mutates local index data.
- The configured prefix can rename these servers. `python -m lct.entrypoint local-mcp --config <path>` remains a direct stdio entry point for the supplemental server.

CGR owns graph construction, Jedi-based Python semantics, vector generation and Qdrant storage. LCT owns only the lexical database, hybrid ranking, configuration, startup and MCP registration. This branch has no independent legacy graph, parser, Voyage embedding or Neo4j implementation.

`tests/test_cgr_retrieval.py` contains focused offline tests for lexical changes, ranking and registration. `tools/cgr_codex_smoke.py` is an optional live Codex MCP probe; run it only with a prepared local installation and index.
