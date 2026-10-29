# Batch 3 dense attachment developer handoff — 2026-10-29

Implemented `attach_dense(c, expected_version, offline=False, expected_program_hash=None, fail_at=None)` in `lct/storage.py`, with `local_code_tools.py attach-dense --version VERSION --expected-program-hash HASH --offline` via `lct/cli.py`. It validates a complete frozen lexical predecessor and its explicit program provenance when executable code changed, reads captured node/file text from the immutable catalog, and uses production `embedding_texts`, `Embeddings.get_many`, normalized partitions and USearch. The captured catalog is copied unchanged into a new candidate; graph, source fingerprint, node/edge counts and lexical postings remain identical. Artifact checksums, current-version fence, lock, and atomic pointer gate publication. Interruption and missing offline cache leave the lexical version current. No source inventory, AST extract, graph analysis, real build, or embedding API request occurred here.

The frozen predecessor hash for the pending real runtime is `59c3b55f4f41d7925172042d31236b8064e9a655895ed06db942ff3d0655b4fc`; the CLI must explicitly receive it because this code changes the executable program hash. Config and schema/model/HNSW checks are independent; the hash is provenance, not a compatibility waiver. Input text ordering is `nodes ORDER BY node_id`, matching the separately prepared cache preflight. Captured UTF-8 BOM files are accepted when their raw checksum includes the BOM; the full catalog checksum remains authoritative. Freshness check time is inherited, with no claim of a new source scan.

Added `tests/test_attach_dense.py`: no inventory/extract/Graph even with source moved; graph/catalog identity and actual dense/exact/RRF retrieval; wrong version and program hash; failed publication and cache miss; BOM; production package/relocated restore. Added offline real-corpus observer `review/dense-acceptance/verify.py` and instructions `PREPARE.md`; it requires a published dense index and actual cached query vectors, and blocks provider calls. Observations are pending actual vector attachment and downloaded-package comparison. Formal review remains 2/3; no push/merge in this handoff.

Verification:

- Targeted initial integration: 9 passed (attachment 2, existing synthetic and portable 7), before BOM/restore additions.
- Fast suite excluding native service file: 444 passed, 18 skipped in 12.36s, before BOM/restore additions.
- Full test attempt: 444 passed, 18 skipped, 3 setup errors because `LCT_TEST_NEO4J_URI` was absent in `tests/test_neo4j_review_independent.py`; no test assertion failure.
- Final targeted after BOM/restore additions and import formatting: 4 passed in 0.99s.
- Ruff check on changed Python files: all checks passed.

The root owns real cache/credential, production attachment, full native-service regression, independent formal third review, downloadable restore, and final acceptance. The isolated real runtime was not read or modified by tests; its manifest was inspected read-only for baseline facts.
