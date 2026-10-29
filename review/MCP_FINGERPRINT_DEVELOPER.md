# B3-004 narrow MCP startup fingerprint repair — developer freeze

Source snapshot: `lct-staged-import`, supplied base `c6fd24335f3f96387c09ba4897fbce14713db970`, branch `feat/full-business-graph-indexes`. This is a staged copy without `.git`; no commit, push, merge, Neo4j service startup, business graph import, or paid API call was made here. This is the user-authorized narrow reopening of the earlier Batch 2 finding, not a reset of its formal review history. Independent review remains with the root agent.

## Change and boundary

- `lct/neo4j_graph.py`: added `Neo4jGraph.snapshot_fingerprint(namespace, version)`. It validates the explicit scope, opens a READ session, executes exactly one `LCTSnapshot` marker query constrained by namespace, version and `complete:true`, returns only `s.fingerprint`, and raises `ToolError` for absent or invalid fingerprint. It neither calls `_read` nor loads chunks, graph JSON, source JSON, nodes or edges.
- `lct/neo4j_mcp.py`: lifespan captures the scalar marker. Existing exception redaction, driver close and tool handlers remain unchanged. `graph_status` still invokes full `snapshot_info` on demand.
- `tests/test_neo4j_fingerprint.py`: one-query scope/read-mode shape, success, missing/null marker, invalid-scope/no-query cases, and guards against `_read` and `snapshot_info` calls.
- `tests/test_neo4j_http_review_independent.py`: updated fake backend; exercises genuine ASGI lifespan with fingerprint-only startup, `graph_status` full response, normal driver closure, and missing/incomplete startup redaction and closure. The existing secret-error redaction test also passed.
- `docs/NEO4J_HTTP_MCP.md`: clarifies startup verifies the complete graph marker's existence and identity only. It does not compare with an external vector/BM25 expected identity. Full graph/source metadata remains in `graph_status`.

No identity schema migration, retention automation, embedding, parser or storage redesign was attempted. Existing manifest repository commit heads and source provenance are unchanged. The caller's result fingerprint remains the stored graph marker; any future stable combined cross-index identity is outside this repair.

## Verification

Python: `/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python`.

| Command | Result | Raw log |
| --- | --- | --- |
| `python -m pytest -q tests/test_neo4j_fingerprint.py tests/test_neo4j_http_review_independent.py` | 10 passed, 0.60s | `review/fingerprint-fix/focused.log` |
| `python -m pytest -q tests` | Exit 1: 442 passed, 18 skipped, 3 setup errors in `test_neo4j_review_independent.py` because its real-Neo4j fixture directly requires unset `LCT_TEST_NEO4J_URI` | `review/fingerprint-fix/full.log` |
| `python -m pytest -q tests --ignore=tests/test_neo4j_review_independent.py` | 442 passed, 18 skipped, 11.63s | `review/fingerprint-fix/full-no-native.log` |

Native Neo4j regression and its actual driver/query behavior have not been run in this environment. The root agent owns fixed-remote review and native verification after integration. The complete `graph_status` metadata path was exercised through the fake backend; real service validation remains pending.

The startup query costs one marker read and one scalar result independent of snapshot graph/source size. The on-demand status path retains its full metadata cost and behavior. There is no new cache or additional invalidation path; the `complete:true` marker is the existing publication boundary.
