# Batch 4 dense partition helper: development evidence

Baseline supplied by coordinator: `6376f87a736abffcef766b02760b0dece5fa3631`, `feat/incremental-index-updates`. This staged tree has no `.git` directory; commit identity and diff cannot be checked locally. No push or merge.

## Scope and behavior

`lct/dense_update.py` provides `write_partitions(candidate_folder, partitions, embedding, hnsw, prior_folder=..., prior_manifest=...)`. It receives finalized normalized `float32` vectors and ordered node-ID mappings; there is no embedding call. It constructs one prior partition lookup keyed by `(repository, kind, is_test)`, validates embedding identity, metric and HNSW settings, compares exact `.npy` and `.json` candidate bytes, verifies three old artifact hashes and sizes, and copies the immutable trio into a new ordinal stem. It never mutates the predecessor. Missing, malformed, corrupted or incompatible predecessor partitions fall back to a rebuild of the affected partition. Changed partitions create a fresh USearch index with current `Index(... metric='cos', dtype='f32', **hnsw)` and sequential `uint64` keys. It returns specs in the existing reader shape and explicit reused/rebuilt counts. The public storage build still needs to call this helper; no claim of build-level reuse until integrated.

USearch incremental mutation of changed partition rows is not used because row deletion/reassignment semantics and serialized search correctness have not been proved. This is partition-level reuse and partition-local rebuild.

| Path | Work and evidence |
| --- | --- |
| Cold build | One USearch construction and add per partition, row array serialization. |
| Exact hit | One semantic lookup, three predecessor artifact hash reads, exact current `.npy`/`.json` representation comparison, three copies; no USearch construction/restoration. |
| Related edit | Rebuild changed partition, copy unchanged partitions. Synthetic add/delete/vector update/mapping update tested against real restored USearch search and exact dot scores. |
| Unrelated added partition | Reuse survives ordinal shifts; prior bytes remain unchanged after new candidate preparation. |
| Unrelated data growth | With 24 prior partitions and one target, instrumentation observes exactly the target's three old artifact reads; others are indexed as specs once but not opened. |
| Corruption/config changes | Corrupt old `.usearch` rebuilds one partition; changed model or HNSW rebuilds all participating partitions. Duplicate semantic prior keys disable all reuse. |
| Rollback/old view | Candidate folder is distinct and predecessor is copied rather than mutated; publication and old-version retention remain the caller's responsibility. |

Validation: `dense-targeted.log` records 4 passing offline tests using real USearch 2.26.6. `dense-ruff.log` records Ruff passing. No full repository regression, public build integration, real graph, paid API, scale test or remote commit check in this scoped helper stage. No confirmed P0/P1 issue.
