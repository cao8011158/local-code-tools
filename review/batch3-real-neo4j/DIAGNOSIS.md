# Batch 3 business Neo4j bounded diagnosis (read-only)

Scope: static call-chain inspection and pure Python byte counts from the validated SQLite/manifest, version `20261028T122745-62019ae507`. No Neo4j process, source rebuild, production change, or paid call was made. The previous two resource failures remain recorded in `ACCEPTANCE.md`.

## Measured serialized data

UTF-8 `canonical` JSON, using the production serializer:

| Component | Bytes | Records |
| --- | ---: | ---: |
| Nodes | 8,901,369 | 5,957 |
| Logical edges | 27,174,982 | 42,459 |
| Graph metadata including sites | 61,164,381 | 22,416 sites |
| Sites array alone | 61,164,004 | 22,416 |
| Graph metadata excluding sites | 368 | — |
| Source metadata | 101,913 | — |
| Whole canonical snapshot payload | 97,342,683 | — |

Site field values (excluding JSON keys and delimiters) total 35,288,890 bytes for `evidence`, 9,493,008 for `resolution_decision`, 2,351,660 for `execution_owner`, and 2,350,386 for `lexical_owner`. These fields describe distinct provenance/semantics, though they may share values in individual sites. The source has 10,341 UNKNOWN-origin sites and 10,376 UNKNOWN-origin edges; `analysis_limited=true`. The site array is 61.164 MB because it holds full evidence, not because the importer copies the array onto every node or edge. `zlib.compress(canonical(graph).encode(), level=6)` measured 3,372,243 bytes in 0.42 s in this process; this is a feasibility measurement, not a tested Neo4j storage migration. Raw counts and byte breakdown are in `.tmp/batch3-real-neo4j/size-breakdown.json`.

Node and edge entities each store `raw_json` plus selected properties (`node_id`, `kind`, repository/path/qualname/version; edge ID/kind/endpoints/status/site/UNKNOWN/version/internal). This duplicates values within those entities by design to support filtered Cypher reads while preserving exact raw roundtrip. Native relationships additionally store edge ID and scope for indexed-node endpoint pairs. We found no accidental second full `graph_json` property or repeated 61 MB site payload per record. The per-entity indexing duplication is real but removing it would change query behavior and is not established as unnecessary. The importer also holds the snapshot payload, prepared record batches, and canonical graph parameter in Python during its call; the 716.8 MiB error is Neo4j transaction memory, so Python retained bytes alone do not explain it.

## Atomic import and observed limit

`Neo4jGraph.import_snapshot` validates counts, kinds, IDs and fingerprint, prepares bounded batches, then executes one `begin_transaction(timeout=300)` for the scope marker, all nodes, logical edges, native relationships, and final `graph_json`/source/count/`complete=true`. Schema constraints are created beforehand and may remain. On a transaction error the records roll back; the first failed namespace was queried and had zero scoped records before retry. The second import reached commit and failed with Neo4j `dbms.memory.transaction.total.max=716.80MiB`, 715.0 MiB already in use. This confirms the owned 1 GiB-heap test environment cannot commit this full transaction. It does not establish an algorithmic correctness defect, a universal minimum heap, or failure on a larger service. Splitting the writes into independently committed batches would violate the existing all-or-nothing publication contract, even if a final `complete` marker hid interim data from normal reads.

The 61 MB `graph_json` assignment occurs at the end of that same transaction, so its stored representation contributes to the transaction's peak, alongside roughly 48,000 node/edge creations and native relationships. The two runs do not isolate which component crosses the limit; the first failed during edge writes at 268.8 MiB, the second at commit at 716.8 MiB. Do not assign the entire peak to sites or claim compression alone guarantees success.

## Confirmed local read cost

The static public call chain is unambiguous: `lct.neo4j_mcp.create_app` lifespan calls `graph.snapshot_info(namespace, version)` during startup and then retains only `info["fingerprint"]`. `snapshot_info` fetches `s.graph_json` and `s.source_json` and runs `json.loads` on both. For this real graph, startup therefore transfers/parses at least the 61,164,381-byte graph string and constructs the 22,416-site list, only to discard it. This is a **confirmed unnecessary full read for a fingerprint-only local request**, owned by the Batch 2/3 Neo4j MCP integration, not a parser/core-dependency limitation.

The MCP `graph_status` tool also calls `snapshot_info` anew on every request, returning `graph` including all sites plus source. Thus each call transfers/parses and serializes the full 61 MB inventory into its response; repeated status calls repeat this work. Here the whole site inventory is part of the documented/current `graph_status` response, so it cannot be silently omitted while claiming the same API. The acceptance script now includes the actual status roundtrip check, but real-service MCP execution did not reach it due to import failure. Static code and real serialized bytes establish the behavior, not its HTTP latency or peak client memory. Node and relation queries call `_read` for a small fingerprint guard and bounded records, rather than `snapshot_info`.

## Minimal executable remedies and ownership

1. **Locality fix without API change:** add a `snapshot_fingerprint(namespace, version)` (or `snapshot_header`) method that executes the complete-scope guard and returns only fingerprint, then use it in MCP lifespan. Preserve `snapshot_info` and `graph_status` behavior. Add a spy/unit test that fails if lifespan calls `snapshot_info` or fetches `graph_json`; test missing/incomplete scope still refuses startup. This is within Neo4j/MCP integration, requires independent review, and does not touch the parser or transaction contract.
2. **Import resource decision:** run the unchanged atomic importer once in a separately authorized, sufficiently provisioned owned Neo4j environment and measure transaction peak, elapsed time, rollback and exact roundtrips. Alternatively, explicitly scope an importer design change, e.g. versioned compressed graph storage with transparent decoding and raw fingerprint preservation, plus migration/compatibility tests for existing namespaces. The measured zlib ratio suggests reducing the final property is promising but does not prove transaction success. Retain one transaction or define and prove equivalent atomic visibility/rollback semantics; do not make per-batch commits as a routine fix.
3. **Status API decision:** if small status requests matter, add a separate bounded summary and paginated site retrieval (or a new explicit `include_sites` contract) while keeping current `graph_status` intact until consumers migrate. Pagination must preserve site order, UNKNOWN/reasons/source identity, version/fingerprint scope and completeness. Changing the existing tool response to drop sites is a behavior/API change needing an explicit decision. The first locality fix is independent of this public API decision.

Classification: the **import failure is a confirmed configuration/resource limit in the owned test service**; resource sufficiency and any importer redesign remain unproven. The **MCP startup fingerprint-only full read is a confirmed local-access defect** in this step's Neo4j integration. `graph_status`'s full read is a documented contract cost and an optimization opportunity requiring API design, not a proven correctness defect or confirmed P0/P1. No core external component replacement is indicated by these observations.
