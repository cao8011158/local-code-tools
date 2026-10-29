# Batch 3 real lexical graph / Neo4j / Drive recovery acceptance

Tool production commit: **5c413c4bceed0093f3054a913199607b74ae4495**. Existing branch feat/full-business-graph-indexes; target feat/local-code-tools-import remains655b78a834c40542bf62c09bdd508c17d7f46450. No production code changed in this phase. Formal Batch3 review count stays2/3; this is partial feature acceptance, not a third full review or merge gate completion.

## Source and offline build

445 files,7,295,748 bytes,286 Python;247 exact-hash local copies and198 pinned Git blob fetches. Source heads and constraints are documented in SOURCE_RECOVERY.md. All configured membership and hashes verified. Captures are not Git checkouts.

One offline lexical-only build completed: version **20261029T111748-7a235bf36f**,5,957 nodes,42,492 logical edges,22,416 sites. Manifest build time234.37s; full CLI child elapsed265.03s including output/exit overhead. No paid embedding or LLM calls. Dense-ready=false; no vector/HNSW quality claims. Graph analysis hit its20,000-association limit;10,343 sites have unknown_origin. This is explicitly incomplete call analysis.

Historical graph statistics were42,459 edges/10,341 UNKNOWN sites. The original full artifact was lost in an earlier environment refresh, so a record-level differential is unavailable. The current count difference cannot be claimed identical to the earlier five external-candidate differences; neither is it proof of a new parser defect. Transport/restore correctness below is checked against THIS fixed published snapshot, not asserted semantic equivalence to that missing snapshot.

## Workspace sidecar interruption and recovery

Immediate normal backup rejected a38,400-byte catalog.sqlite-journal. The original was not deleted or opened for recovery. Main catalog SHA2567d260089cb4cfa45f4105509cb10283bbc2fd48504b54cebfad92ff61e2508e4 and523,264,000 bytes matched the published manifest; immutable read-only integrity_check=ok and counts matched. The journal and two synchronization-like temporary files remained. Post-publication filesystem reappearance is plausible but not proven. Production source-side sidecar rejection was retained.

Preserved a diagnostic raw checkpoint in Drive, explicitly UNVERIFIED/not a normal restore package. Constructed an explicit recovery transport from manifest-verified main/catalog metadata and fixed program, preserving the rejected source. Frozen vector main/WAL/SHM had equivalent schema and zero vectors; the final recovery uses SQLite backup from a WAL-aware frozen copy. Production restore then validated and rebound the recovery transport into /tmp/lct-b3-isolated-v2-20261029, outside synchronized storage. Production backup SUCCEEDED there without disabling sidecar validation. Detailed diagnostic limits and the one-off recovery script are retained.

## Actual Neo4j acceptance

Owned Neo4j5.26.0 launched with Java-Xmx1024m; configuration SHOW SETTINGS still reports server.memory.heap.max_size384MiB (configuration unchanged), transaction total limit716.80MiB. No JVM/transaction peak was measured this run.

- Full business import **24.305s**,235 data batches:15 node,85 logical-edge,56 native-relation,79 metadata. Maximum500 records; maximum summed record JSON bytes1,048,043, within1MiB.
-5,957 nodes and42,492 logical edge records read back exactly;27,138 native relationships matched IDs/types/endpoints;15,354 boundary logical edges retained.
- Full graph metadata61,238,037 bytes and source metadata round-tripped exactly. UNKNOWN flags, source commit identities, complete publication marker and scope isolation preserved.
- Idempotent reimport **1.951s**; filters for module/class/function and repository passed. All database checks completed46.106s after start.
- Initial combined run stopped at HTTP client construction: inherited SOCKS proxy needed unavailable socksio. Original FAIL record preserved in neo4j-acceptance.json.
- Cleared proxies only in local acceptance child, reused already imported graph, reran only MCP. Four read-only tools passed; startup did not invoke snapshot_info before explicit graph_status. Anonymous request rejected; fixed scope enforced. MCP-only run **16.67s**, no reimport. Native service shut down by owned launcher.

## Persistent package and actual restoration

Source capture ZIP2,628,775 bytes uploaded and downloaded with equalSHA2564711b4808c355a54c27743d11694d1521903a821cb2636c97d2af19e424d5d59.

Normal toolkit/lexical package **67,417,228 bytes**,SHA256 **f0bdb2309c9fc349207593bbd45d1ed6dce2df6cb967ee5516fa127acd96ae01**, uploaded and downloaded with equalhash. Drive id18fmZ5EqHeGwAmWPEeshf2Z0nw1VIDMO4. It contains the tool, authoritative SQLite graph/source,manifest and BM25, NOT a physical Neo4j store or generated vectors. Neo4j projection is recreated by the validated importer.

During downloaded-package production restore, original source roots and original isolated data directory were temporarily unavailable. Restoration into a new directory succeeded. Separate subprocess loaded only the restored toolkit modules and verified equal module/class/function BM25 results, document search, selected indexed source hashes, source commits, artifact hashes, graph metadata hash and bounded relations. Source lookups reported indexed_snapshot with no live files. Originals restored in finally. Installed Python dependencies were shared; this is relocation acceptance, not clean-machine package installation. Results in portable-acceptance.json and lexical-before/after.json.

## Outstanding gates

Actual Voyage vectors,HNSW/dense/RRF evaluation and final complete package remain unverified. Existing parser incompleteness/count variation must not be concealed by transport success. No merge and no final Batch3 pass. Expensive artifacts now have real Drive copies. Raw evidence failures and successful resumed stages remain separate.


## 2026-10-29 next-stage readiness

Real graph, BM25, Neo4j import, HTTP MCP and downloaded-package relocation checks are complete for the frozen snapshot; this is not final Batch3 approval. Vector preparation:4070 chunks,4068 unique inputs,79 document batches excluding retries,11 query cases. Ten cases have labels; the RE case has two matching nodes and mixed has no relevance label, so neither may be silently treated as a unique gold answer. Configured historical price gives USD0.6098874 conservative estimate, not measured provider tokens/current quote. No paid request made. Current runtime credential absent; bounded paid run remains pending. Formal review count2/3, no merge.
