# Latest checkpoint — real lexical graph accepted, dense pending

Production fixed at 5c413c4bceed0093f3054a913199607b74ae4495. Version20261029T111748-7a235bf36f:5957 nodes/42492 edges. Actual Neo4j bounded import, four HTTP MCP tools, Drive upload/download hash check and restore without original sources/data passed. No production modifications in this phase; formal Batch3 reviews remain2/3. No merge. Sidecar rejection/recovery and parser incompleteness are explicitly documented in business-resume/ACCEPTANCE.md.

Normal lexical toolkit package: Drive18fmZ5EqHeGwAmWPEeshf2Z0nw1VIDMO4,67417228 bytes,SHA256 f0bdb2309c9fc349207593bbd45d1ed6dce2df6cb967ee5516fa127acd96ae01. No vectors yet. Source capture also persisted. Do not reparse the sources for the next stage.

Next: authorized bounded Voyage embedding, HNSW/exact and RRF quality checks, final package acceptance and remaining independent review. Current runtime has no VOYAGE_API_KEY. Offline estimate4068 unique inputs/79 batches without retries; configured historical-price estimate USD0.6098874 is not current billing quote. Paid calls0. Existing task record requires bounded run budget before paid execution.

## Historical checkpoints (preserved)

# Latest checkpoint — startup prerequisite repaired

B3-004 closed at `caa9d1ee6c54187580061eb90932e72d578e83e4`, independently reviewed after user-authorized narrow Batch2 reopening. Native full suite462 passed/1 skipped,72.47s. Preserve original Batch2 3/3 plus this one authorized extra review; Batch3 remains2/3. No merge. Next: real business graph regeneration, durable persistence before import, actual import/retrieval/restore acceptance. No paid API in this repair. See MCP_FINGERPRINT_REVIEW.md.

## Historical checkpoints

# Latest checkpoint — staged importer reviewed

Implementation `cb68331465cde30bf7333b0f41759669bf4ccb8d`; formal review **2/3**. Independent tests:452 passed/1 skipped. Synthetic61.16MB evidence import/readback passed with bounded committed batches; sampled retained transaction heap maximum2MiB. Not full business-data acceptance. No merge or paid API calls. See BATCH3_REVIEW_ROUND2.md. Batch2 B3-004 remains paused pending explicit narrow reopening under the three-round rule.

## Previous checkpoint (historical)

# Current checkpoint — staged-import redesign in progress

Source base: `56a04275bc72c982559e1b47b82af541d10dd40d`; branch `feat/full-business-graph-indexes`; merge target unchanged at `655b78a834c40542bf62c09bdd508c17d7f46450`. Formal reviews completed: **1/3**. No merge; no new paid API calls.

The user authorized the staged-write / atomic-publication design after reviewing the memory diagnosis. Current repair changes import transactions, not source analysis. Same-version retries must be fenced and unpublished until content verification completes. Separate MCP startup P2 remains open. The preserved report below is historical: its `/tmp` real graph has since disappeared and is not recoverable from current files. Fixed source SHAs and build evidence remain available. Prior interpretation of the user's continue instruction regarding five UNKNOWN external candidates is documented in STAGE_REPORT; do not manufacture explicit waiver wording.

## Historical checkpoint (retained verbatim)

# Batch 3 checkpoint — round 1 completed, human disposition pending

Working branch: `feat/full-business-graph-indexes`.
Reviewed implementation: `42b0acd95fd503551c22447613738c8d9e62bfe9`.
Merge target: `feat/local-code-tools-import` at `655b78a834c40542bf62c09bdd508c17d7f46450`.
Formal reviews completed: **1 of 3**. No merge. Latest report-only commit does not imply a new review or reset the count.

User approved both narrow prerequisite repairs and requested resumption after locality-review installation. Production changes are in python_analysis.py, storage.py and management.py; three business repositories remain unchanged.

B3-001 repeated candidate scans: repaired with conservative observed-query and exact definition-line indexes. Actual query calls 2,226,366 -> 973,785; admission checks 1,674,750 -> 422,169; same 28,010 misses. Graph analysis 245.487 -> 212.531 seconds. Cold inference and unknown fallback cost remain; no memory improvement.
B3-002 artifact membership: repaired using explicit catalog/partition files, streamed hash/size, sidecar rejection and backup exclusions. Actual offline build published 5,957 nodes / 42,459 edges / 22,416 sites in 230.903 seconds. No embedding requests, dense_ready=false.

Fixed-remote independent regression with real Neo4j: **441 passed, 1 skipped, 44.55 seconds**. Twelve synthetic differential pairs agree. Five independent dense/backup/WAL boundary cases passed and are in the remote test suite. See BATCH3_REVIEW_ROUND1.md and batch3-round1/ for complete evidence.

## B3-003: existing core inference variability; human decision required

All actual internal target sets, completeness and UNKNOWN flags match. Five external-boundary site records differ at scale.py config.get lines 80,82,146,152,155. Same baseline code/source/fixed hash seed/query order also varies between no-result and builtins.dict.get across bounded fresh processes. Precise cause remains unverified; do not claim a proven optimization regression or upstream defect. All five remain incomplete UNKNOWN.

Recommend accepting this narrowly documented external-candidate variability and continuing Batch 3 with explicit UNKNOWN/coverage limitations. Alternative: authorize a separate bounded core stability investigation before continuing. Existing scope authorization covered locality and artifact membership, not replacement or broad rewriting of the core analyzer. The root has stopped affected automatic progression under batch-dev-review; await actual user choice.

Both full runs hit the original 20,000 association limit and report analysis_limited=true. This is a final coverage limitation, not authority to raise budgets or certify complete calls.

## Preserved artifacts and remaining gates

New validated lexical graph runtime: /tmp/lct-b3-locality-fixed-20261028, version 20261028T122745-62019ae507.
Original failed synchronized-workspace candidate preserved unchanged. Runtime data is transient and is not uploaded as a final accepted package. Reproduction scripts and statistical evidence are in the repository; no real database/index/key uploaded.

Remaining: full feature/real data acceptance, actual vectors/HNSW, real business Neo4j projection, Drive restore. Paid Voyage budget still pending; zero authenticated API requests. Existing conservative initial embedding estimate remains <= USD0.6099, account/free quota unknown. No auto-merge until human disposition and all gates pass.
