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
