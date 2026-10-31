# Optional certified dictionary projection — development record

Base: `793ca38b6228d15047ed7eb2c69116ed61680fcc`, branch `feat/incremental-index-updates`. This staging directory is not a Git checkout. No push/merge or real repository build occurred.

## Scope and result

`lct/neo4j_graph.py` reads the already validated immutable `graph-sites` sidecar when its manifest advertises schema 1 and `certified-dictionary-v1`. The v3 canonical fingerprint includes sorted value nodes, edges, and read subscriptions alongside the original four code fields. The v2 canonical four-field payload is unchanged. Partial/old sidecars remain v2 and explicitly report `unprojected-partial` rather than a complete empty value graph. Certified zero-record sidecars may be v3 with verified zero counts.

The staged importer creates scoped typed `LCTValue` nodes, raw `LCTValueEdge` records, and typed native support relations; callable endpoints are the existing `LCTNode:Function`. `READS` raw records include the source consumer repository/path. It checks identity/endpoints/subscription equivalence and a 20,000-record safety ceiling before import. Bounded writes, ownership fencing, incomplete-marker visibility, scoped cleanup and retry, and verification of all records, native endpoints, counts, labels, chunks and hashes precede the atomic complete marker. A complete v2 scope cannot be rewritten to v3; use a fresh namespace/version. Existing v1→v2 maintenance initializes the new zero/status marker fields. `native_count` is total native code plus value relationships, with code logical `edge_count` and value counts separate.

The driver exposes `get_value_nodes(namespace, version, ids, expected_fingerprint)` and `get_value_relations(namespace, version, ids, expected_fingerprint, types=None, direction='both', limit=100, cursor=None)`. Known value or function IDs use scoped identity indexes and native adjacency, followed by an indexed raw edge join. Both reject missing/partial/wrong-fingerprint markers; pages have lookahead and reply byte limits. Code relation reads use their native query for both v2 and v3 and filter to code relation types.

`lct/official_mcp.py` adds `value_read_cypher_requests`, `value_node_read_cypher_requests`, and value raw-fragment modes, all with explicit v3 complete marker/fingerprint guards. Existing code templates accept an optional explicit v3 schema while defaulting to v2. It remains fixed read-cypher inputs for the official server; no custom or write MCP operation was added. `lct/publication.py` binds and verifies the actual schema and value counts, while preserving previous v2 descriptor compatibility. Documentation status is in `docs/NEO4J_FULL_GRAPH.md`, `docs/OFFICIAL_NEO4J_MCP.md`, and `docs/INCREMENTAL_UPDATE.md`. Focused tests are `tests/test_neo4j_value_projection.py`.

## Verification

- Initial focused historical tests: `10 passed, 11 skipped` in `value-projection-targeted-initial.log` (first shell's bare `pytest` command was unavailable; `.venv/bin/python -m pytest` used afterward).
- New offline/template/publication tests: `12 passed` in `value-projection-focused.log`.
- Root-authored independent fingerprint preflight, read only: `3 passed, 3 deselected` in `value-projection-independent-preflight.log`.
- Owned synthetic Neo4j 5.26.0/APOC 5.26.0 initial targeted service tests: `7 passed` in `value-projection-service-initial.log`.
- Fast full suite, once: `581 passed, 27 skipped` in `value-projection-alltests.log`. This was before a final narrow typed-node/endpoint verification predicate; the owned-service targeted rerun after it was `6 passed` in `value-projection-service-final.log`.

The parent owns the independent offline and service cases, actual official MCP process and EXPLAIN/PROFILE expansion measurements on the frozen upload. No production credentials or data were used.

## Limits

This projects only existing certified dictionary records. It does not infer new callable targets, certify broader Python, add value nodes to embeddings/search, or change the SQLite update algorithm. V2/legacy projections remain code-only. Public code queries do not return value relationship kinds. The official MCP guard is a query predicate, not an authorization boundary; its server/database privileges must enforce read-only access. Neo4j runtime/profile results here cover synthetic captured fixtures, not a business-scale performance guarantee.
