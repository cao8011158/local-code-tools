# Official Neo4j MCP graph reads

Known-node graph reads use Neo4j's **official** `neo4j/mcp` server, pinned here to `neo4j-mcp-server==1.6.1` (the executable installed by that package is `neo4j-mcp-server`). It exposes `read-cypher`; run it with `NEO4J_MCP_READ_ONLY=true` and `NEO4J_MCP_TELEMETRY=false`, and point `NEO4J_MCP_DATABASE` to the explicit database. The server requires APOC core. Use a database credential with read privileges for the query service. The official server chooses the database, but it does **not** enforce an LCT namespace, version, or fingerprint: those are explicit parameters and predicates in each fixed template, not an authorization boundary. Do not grant arbitrary query clients access to other sensitive data in the same database.

The project does not wrap or reimplement the MCP server. Obtain validated `read-cypher` tool inputs from the installed project code:

```sh
python -m lct.official_mcp --namespace '<existing-namespace>' --version '<published-version>' \
  --expected-fingerprint '<64-character-snapshot-fingerprint>' --direction both --limit 16 '<node-id>'
python -m lct.official_mcp --namespace '<existing-namespace>' --version '<published-version>' \
  --expected-fingerprint '<64-character-snapshot-fingerprint>' --entity nodes '<node-id>'
```

Call the returned `read-cypher` requests in order. Require **exactly one** marker row with the expected fingerprint, code node count, logical edge count, and boundary count. A missing marker is an error (missing, incomplete, old projection, or wrong fingerprint), not an empty graph. Then consume the second request. For relation pages, the result contains `id`, original `raw` edge JSON, `source_boundary_id`, `target_boundary_id`, and fingerprint; display at most `min(limit,16)` rows. When the extra lookahead row is present, set `--cursor` to the **last displayed row ID**, not the lookahead ID; the lookahead is fetched again on the next page. An input limit above 16 still has an effective page size of 16. A row with `raw_too_large=true` has a null `raw` field; request `--entity edge-fragment --offset 0 <edge-id>` (or `node-fragment` with a code node ID), then advance the character offset by the returned fragment length until the returned `length` is reached. Verify the marker and fingerprint on every fragment. The official template caps at 17 database rows and suppresses each raw JSON property over 65,536 characters; it does not promise a 64 KiB total MCP reply. Node requests accept at most 16 IDs per call; split larger sets into batches. The raw edge retains `UNKNOWN`, `complete`, `unknown_origin`, candidates, site/reason, and original source/target identities; a boundary node does not resolve an uncertain call.

`LCTNode` records are original source-code nodes. `LCTBoundary` records represent non-code endpoints. A meaningful external endpoint string receives one stable `external:<original-endpoint>` boundary ID in this namespace/version. A null/unknown endpoint receives a distinct `unresolved:<edge-id>:<source|target>` ID, so unrelated call sites never collapse into one Unknown object. Every logical `LCTEdge` has one typed native relationship. The original evidence lives on the `LCTEdge` record, joined by `edge_id`; the relationship type or boundary node alone does not convey `unknown_origin`, `complete`, or call-site reasons. The raw edge and the new physical boundary ID are both returned. For a physical boundary ID from a relation row, use `--entity boundaries '<boundary-id>'` with the same scope/fingerprint. Known-node and external symbol relation inputs use original IDs; boundary lookup uses physical IDs. Results deduplicate multi-ID/self-loop matches and sort by original edge ID. The known-node path starts with scoped identity index seeks and traverses only native adjacency; it does not scan all relationships or source/target edge records.

The existing `lct.neo4j_mcp` transport and `Neo4jGraph` driver reads remain compatibility surfaces. The former is deprecated for new graph querying; it is not the official Neo4j MCP server. The LCT Voyage/BM25 build, update, and retrieval interfaces remain separate and unchanged.

## Offline in-place maintenance

Stop the owned Neo4j MCP query service before maintenance. In the terminal, with existing `LCT_NEO4J_URI`, `LCT_NEO4J_USER`, and `LCT_NEO4J_PASSWORD` configured, run:

```sh
python -m lct.neo4j_graph --config '<config-path>' --database neo4j \
  --namespace '<existing-namespace>' --version '<published-version>' \
  migrate-projection --expected-fingerprint '<original-snapshot-fingerprint>'
```

This command reads the **already persisted** Neo4j node, edge, and evidence records. It does not reparse source, call embeddings, rebuild the SQLite/vector/BM25 index, replace archives, or change the source fingerprint. It first makes the marker incomplete so project reads fail closed. It then adds stable boundary nodes, missing native relationships, and derived boundary IDs in bounded, ownership-fenced transactions. It verifies all original nodes/edges/evidence, counts, physical endpoints, types, and scope before atomically publishing `projection_schema=native-boundary-v2` and `complete=true`. On failure the marker remains incomplete with `state=failed`; repair the cause and rerun the same command with the same fingerprint. A crashed owner must let its lease expire before retry. The command is idempotent and does not delete old source graph records. It recomputes the canonical fingerprint in persisted ID order, as produced by the normal source snapshot pipeline; an ad hoc historical import whose input arrays used a different order is rejected safely rather than re-fingerprinted. Arbitrary Cypher outside these project templates can still bypass the marker; do not run the official query service during maintenance. Restart it only after successful verification.

`maintain-indexes` is also a terminal/offline driver command. Identity constraints, including the boundary identity, are idempotent. `--legacy-edges` optionally installs `(namespace,version,source)` and `(namespace,version,target)` edge indexes only for the legacy compatibility query path; v2 native traversal does not use them. Neither command is a retrieval MCP tool. New imports create v2 projections directly; an existing complete v1 scope is never silently replaced by import.
