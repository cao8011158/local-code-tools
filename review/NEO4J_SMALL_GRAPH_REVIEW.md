# Batch 1 independent review — PASS

Date: 2026-10-28. Formal review round: 1 of maximum 3.

Baseline: `7f3c2d025b972225367463a5cb619f2480905223`.
Reviewed implementation: `2cd3c41e1d1a17a9bca88b9f2d3a35bd2ea7146e` on `feat/neo4j-small-graph`.
The seven changed files were fetched back from GitHub at this exact commit and their Git blob hashes verified. Unchanged source/tests came from the baseline snapshot previously verified against GitHub. This was a separate review directory, not a full Git clone.

## Scope and result

No blocking findings within the bounded small-graph scope. No parser, existing stdio MCP, query/ranking, embedding or business repository changes. Added real Neo4j projection preserves the source graph's raw nodes/edges, conservative UNKNOWN evidence, source revision metadata and explicit namespace/index-version boundaries. Internal edges have native Neo4j relationships; external/null endpoints retain logical edge records without fabricated code nodes.

Independent run: **6 passed in 10.78s**, with Neo4j Community 5.26.0, Java 17, neo4j Python driver 5.26.0, Python 3.12.14. No skips. Tests used an owned synthetic database with bounded JVM heap (384 MiB) and page cache (128 MiB); the service was stopped afterward.

```sh
uv sync --locked --group neo4j
# Start an isolated Neo4j 5.26 service and set LCT_TEST_NEO4J_URI,
# LCT_TEST_NEO4J_USER, LCT_TEST_NEO4J_PASSWORD, LCT_TEST_NEO4J_DATABASE.
pytest -q tests/test_neo4j_small_graph.py tests/test_small_graph_mcp_e2e.py tests/test_neo4j_review_independent.py
```

Coverage: 17-node/30-edge fixture import and JSON roundtrip; function/class/module and repository filters; every relation type and direction; UNKNOWN sites and reasons; source Git revision; missing-version errors; idempotent import and conflicting-content rejection; namespace/version isolation; injected write failure with no partially published snapshot; existing stdio MCP protocol regression. Three additional independent tests cover internal/external/null/self edges, sorted mixed-result truncation and `has_more`, native relationship counts, literal special-character namespace values, duplicate/missing node requests, concurrent same-snapshot imports, and invalid duplicate identities failing before publication.

The first review launch hit a missing temporary-directory parent before any test body executed. Creating that parent fixed the harness; no application source change was required. Developer evidence (3 passed in 10.61s) is separate from the independent run above.

## Limits and next gate

This passes Batch 1 only. Maximum 500 code nodes and 5000 logical edges; full sites are stored as JSON. No full-size performance, incremental update, paid embedding call, real business-index migration, public HTTPS endpoint or ChatGPT-connected remote MCP was tested. Existing unrelated full-suite assertions were not rerun or claimed to pass. SQLite remains authoritative. Batch 2 must validate authenticated HTTP MCP on the same small graph, and must distinguish a transport test from actual ChatGPT tool attachment.

The subsequent evidence commit adds this report and independent tests only; it does not alter the reviewed implementation or lockfile. User has authorized merge after review/acceptance PASS. The repository's current default branch is `feat/local-code-tools-import`, not `main`.
