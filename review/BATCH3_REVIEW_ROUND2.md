# Batch 3 — independent review round 2 of 3

Reviewed implementation: `cb68331465cde30bf7333b0f41759669bf4ccb8d` on `feat/full-business-graph-indexes`. Remote branch head, importer content and Git blob identities were re-read. The independent working snapshot used 107 byte-matched available tracked files; README newline normalization was corrected from the committed content. Existing installed Python environment was reused: this is not fresh-machine dependency validation.

## Result

The staged-import repair passes this review. No new confirmed P0/P1 or blocking P2 was found in this repair. This is NOT full Batch 3 acceptance and does not authorize merge while its remaining gates are open. Review count is now **2/3**, not reset.

The implementation uses bounded committed batches, fenced marker ownership, immutable validation state and one small publication transaction. All application reads reject an incomplete scope. A failed import can leave hidden candidate rows; same-content retry performs bounded cleanup/restart. This deliberately replaces transaction-wide physical rollback with atomic public visibility. No checkpoint-resume guarantee is made.

## Independent execution

1. Owned native Neo4j 5.26.0, 384 MiB JVM heap; `python -m pytest -q tests --junitxml=review/staged-import/independent-tests.xml`: **452 passed, 1 skipped, 1 warning in 69.30 seconds**. Skip is the explicitly optional real-cache test. Warning is existing HTTP MCP client deprecation. This includes the four independent boundary probes, real Neo4j import tests, concurrency, existing MCP checks and parser regression tests. No embedding API calls are allowed by the test fixture.
2. Same fixed importer, owned native Neo4j, 1 GiB heap; `python review/staged-import/memory_check.py`: synthetic 100 nodes / 500 edges / **61,164,381 bytes** graph evidence. **90 committed transactions**, 82 data batches, 79 metadata batches. Largest batch's summed record bytes **786,780**. Exact graph/source readback passed. Runtime **8.82 seconds**. Maximum sampled retained transaction heap after data writes **2 MiB**, versus about126.3 MiB in the preceding single-transaction synthetic probe of comparable evidence size. Services were stopped by the launchers.

The memory launcher first exited before service startup because its log directory was absent; after creating that directory, the one actual memory run succeeded. No production change was needed. Samples are transaction estimates after writes, NOT in-query, commit, JVM, Python or real-graph peak measurements. The repeated-character evidence has different structure from actual sites. This establishes bounded-write behavior, not full real-data capacity.

## Independent boundaries

- A complete same-fingerprint scope does not invoke batch preparation.
- A corrupted indexed field with unchanged row counts/raw JSON cannot publish; retry restores correct data.
- A writer replaced after validation cannot publish or release the replacement's ownership.
- If final commit succeeds but its acknowledgement is lost, exception handling leaves it published and retry remains idempotent.

Developer-owned adversarial tests additionally cover UTF-8 chunk boundaries, 8 MiB Unicode readback, missing metadata, corrupt edge data, extra native relationships, expired ownership and hidden partial records. Passing these does not imply arbitrary administrative database mutation is supported.

## Remaining limits / blockers

- B3-006 unnecessary write-batch preparation is closed. Input fingerprint validation still serializes supplied content once; complete-version return does not mean zero input-validation work.
- B3-005 storage repair is verified synthetically; original full business graph import remains unverified. The previous costly graph files are absent after environment refresh. Regenerate only after prerequisites and persist before downstream tests.
- B3-004 MCP startup still calls snapshot_info for just a fingerprint and reads the complete metadata. It is unchanged, belongs to Batch 2 (already 3/3), and needs the explicit narrow reopen required by batch-dev-review. No extra Batch 2 review is implicitly authorized here.
- Full business graph, paid embeddings, retrieval quality and Drive restore acceptance remain outstanding. No business graph rebuilt, paid API requested, real data uploaded, or merge performed.

Evidence: `staged-import/independent-tests.xml`, `staged-import/memory-result.json`, `staged-import/memory_check.py`; developer report: `STAGED_IMPORT_DEVELOPER.md`.
