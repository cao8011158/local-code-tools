# Batch 3 checkpoint — paused for scope decision

Working branch: `feat/full-business-graph-indexes`.
Published implementation candidate: `7c50563cd695aed018bd451dec9d05a631792525`.
Base / current merge target previously verified: `655b78a834c40542bf62c09bdd508c17d7f46450` on `feat/local-code-tools-import`.
No merge. Formal Batch 3 reviews completed: 0; independent source inspection and fast regression were underway, and functional acceptance has NOT passed. User prioritized workflow Skill revision before further production work.

## Completed implementation and verification

The nine changed files add verified captured-source inventory and bounded atomic Neo4j bulk writes. Developer graph tests: 8 focused passed; 418 full passed, 1 skipped. Snapshot developer: 16 focused passed; 419 offline passed, 3 skipped, with service exclusions separately documented.
Combined development fast regression with owned Neo4j: 427 passed, 1 skipped, 41.34 seconds.
Independent copy fetched from the exact published candidate: all nine changed Git blobs verified. Independent real-Neo4j fast regression: 427 passed, 1 skipped, 45.85 seconds (SDK deprecation warning). Shared Python environment; not a clean-machine dependency installation.

Source captures: 445 selected files / 7,295,748 bytes, verified Git blob SHA-1 and SHA-256. Offline extraction: 5,957 nodes, 4,070 vector chunks / 4,068 distinct inputs. No authenticated Voyage request, no paid requests, no dense index, no real-data acceptance or complete graph publication.

## Scale findings (not introduced by the nine-file candidate)

B3-001: existing `Analyzer.parameter` and `registry_arguments` repeatedly inspect global call-site lists through `may_call` / `query`. Initial 240-second probe timed out. A subsequent progress-instrumented run completed all 22,416 top-level call-site adjudications by the 240-second sample, so this was NOT proof of an infinite hang. At that sample: 2,226,366 query calls, 28,010 cache misses and 2,198,356 hits; process peak RSS 1,814,164 KiB. Both expensive cold Jedi work and repeated warm global scans must be distinguished. No evidence that Jedi itself is defective.

B3-002: that run failed after 283.17 seconds before publication in `storage.build` while stat-ing a disappearing incidental `.catalog.sqlite.*` file previously admitted by directory-wide artifact enumeration. Workspace synchronization is a likely source of transient copies, not conclusively identified. The failed catalog also has a journal: immutable quick-check alone does NOT prove safe publication. Candidate remains failed; no current pointer. Preserve this evidence; do not repair the failed real database in place.

## Candidate work retained but not published

A four-file parser locality candidate exists locally: cached-observation candidate index, exact definition-line index, tests and developer report. No eager inference prepass or name-only exclusion; class-construction fallback retained. Developer reports 148 targeted passed, 1 skipped; 417 offline full passed, 1 skipped, 12 service cases deselected. This candidate has NOT received independent review or real-scale equivalence/performance acceptance, and is NOT in the published SHA above.
Artifact-membership diagnosis completed; further storage changes/testing paused at the user's request. No artifact fix accepted or published.

## User's revised workflow boundary

Each developer/refactor/fix completion and each completed formal review must have a substantial user-visible report plus persisted evidence. Findings in earlier batches of the SAME authorized step return to their owning batch without rewriting Git history or resetting the review limit. Confirmed P0/P1, system-code issues OUTSIDE the current step, and defects/critical limitations in CORE external dependencies require human decision. Noncore alternatives remain bounded by existing authorization and contract. Max three formal review rounds remains.

The parser and artifact paths predate this Batch 1–3 feature sequence. Do not silently classify them as Batch 1 Neo4j regressions. Pending user decision: explicitly include the two narrow existing-code repairs in this step, or leave them separate. Existing candidates preserved, affected full-build/merge work paused.

Paid run budget also remains pending. Configured initial vector estimate: <= USD0.6099 using conservative byte-bound inputs at USD0.12/million; actual provider tokens/free allowance unknown. No credential is stored in this repository or any evidence artifact.
