# Batch 3 staged Neo4j importer — developer result

Base: `agentic-trpg/local-code-tools` `feat/full-business-graph-indexes` at `56a04275bc72c982559e1b47b82af541d10dd40d`. The working source snapshot is selected Git blobs, not a Git checkout. This is development/self-test evidence; independent review and remote commit verification belong to the root agent. No push, merge, parser, embedding, source, storage, or MCP startup change was made.

## Changes

- `lct/neo4j_graph.py`: input count/kind/identity/fingerprint checks remain ahead of writes. A same-fingerprint complete marker returns early, while conflicting content refuses. Each node, logical edge, native relationship and chunk parameter batch commits separately with up to 500 records/1 MiB serialized input. A write lock on the scoped snapshot marker fences the owner token in each batch and cleanup transaction, with a renewable 60-second lease and 10-second concurrent wait. A same-content retry claims an unowned/expired incomplete marker, removes only its own scoped candidate in bounded commits, then starts over. Ordinary failure releases ownership and keeps incomplete records hidden. Chunked UTF-8 graph/source JSON avoids a single large marker property. Marker expected counts/hashes and per-chunk SHA-256 are checked alongside exact stored node/index fields, edge fields/raw JSON, native relationship identities/endpoints/scope, and chunks before a small atomic complete=true publish. Existing complete graph_json/source_json markers remain readable; current snapshot_info reassembles chunked metadata.
- `tests/test_neo4j_bulk_import.py`, `tests/test_neo4j_small_graph.py`: failure expectations now assert hidden partial records and retry, retaining the original fault injector; batch query count allows marker fencing while retaining a bounded formula.
- `tests/test_neo4j_staged_import.py`: 8 MiB Unicode metadata roundtrip, UTF-8 boundary, tamper/missing chunk/extra native relation refusal, retry cleanup, complete cleanup refusal, expired owner fencing.
- `README.md`, `docs/NEO4J_FULL_GRAPH.md`, `docs/NEO4J_SMALL_GRAPH.md`: staged publication, visibility, lease, cleanup/restart and bounds. Root-authored `tests/test_neo4j_staged_independent.py` was included in execution, not edited here.

## Validation

- Owned native Neo4j Community 5.26.0 launcher with bounded JVM heap, Python `/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python`: `pytest -q tests/test_neo4j_staged_independent.py tests/test_neo4j_staged_import.py tests/test_neo4j_bulk_import.py tests/test_neo4j_small_graph.py tests/test_neo4j_review_independent.py` — **19 passed in 44.59 s**, after final metadata hash changes. Service stopped by launcher.
- `pytest -q tests` — **451 passed, 1 skipped, 1 failed** in 53.24 s. Failure at `tests/test_lifecycle.py::test_registration_preserves_others_and_is_idempotent` was selected snapshot environment setup: `register_mcp.py` initially missing and then local `.venv` missing. After restoring exact tracked Git blobs (root action) and linking local `.venv` to the existing isolated environment, single failed test passed (**1 passed**). This is not a claim that the full product suite was rerun successfully.
- Bare `pytest -q` collects separate experimental tests requiring `psutil`; it was attempted once and blocked by that missing optional package. No full business graph was built and no paid API invoked.

## Limits and review points

- Per-query driver fetch size is 64. Verification streams query cursors, but the database may sort indexed result streams; no production memory or throughput guarantee was measured. The 8 MiB metadata case demonstrates chunking and exact roundtrip, not a 61 MiB business snapshot acceptance. The 300-second verification transaction holds a marker lock while comparing rows so takeover cannot interleave; final publication uses a separate small fenced transaction. Other database-admin mutations outside importer ownership are not part of the writer contract.
- Retry is cleanup/restart, not checkpoint resume. The marker records `writing`/`validating`/`failed`/`complete`; persisted candidate records show partial work, but no per-batch checkpoint counter is promised.
- Independent fixed-commit review remains outstanding. No P0/P1 was confirmed during development. Existing startup defect in `lct/neo4j_mcp.py` is outside this batch and untouched.
