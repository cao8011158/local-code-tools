# Batch 2 final independent review and Work restore acceptance

Date: 2026-10-28 (Asia/Shanghai). Formal review round **3 of 3**. The original two rounds remain in `NEO4J_HTTP_MCP_REVIEW.md`, `BATCH_1_2_RETROSPECTIVE_REVIEW.md` and the retained evidence ledger; no counter reset.

Repository: `agentic-trpg/local-code-tools`. Branch: `feat/neo4j-http-mcp-small-graph`. Repair base: `64573251c13b7ef86f0ab343b209879f7edd5a52`. Reviewed repair commit: `e5b275ae99962b8de4e65c872268a3eeeedcb411`. Default merge target remains `feat/local-code-tools-import` at `3d06e10744d02fb5882d407aa1accd54dd62b848` before merge. Root reviewed independently of the GPT-6 SOL / medium implementation agent. Six changed files were fetched from GitHub at the exact repair commit and checked against Git blob hashes in a separate source snapshot. This is not a clean Git clone or fresh dependency installation.

## Finding and resolution

RESTORE-001 (P2) is addressed. Previously, changing the runtime data directory invalidated the configuration identity. Schema-2 backup now captures normalized configuration and program/config/index-format evidence. Restore checks archive membership/path safety/checksums, captured executable fingerprint, active version compatibility and retained artifact integrity before staging a new installation. It changes only the runtime data path and the config hash of compatible manifests, recording the original and new identities. Ordinary query compatibility checks were not weakened. Retained incompatible versions are not silently promoted. Source versions, graph nodes/edges/sites/UNKNOWN information and all index artifact bytes remain unchanged. No source rebuild or Embedding request is used for relocation.

The independent review inspected the whole Batch 2 change from its Batch 1 base, including fixed-scope read-only MCP behavior and the prior contract-alignment changes. The bounded small-graph implementation has no confirmed P0/P1 or remaining blocking finding. Work-local execution is the accepted use mode; no public HTTPS deployment or native ChatGPT plugin installation is claimed.

## Test evidence

- Developer targeted tests: **4 passed**; developer full suite with owned real Neo4j: **415 passed, 1 skipped**.
- Independent exact-repair-commit full suite: **415 passed, 1 skipped**, 21.48 seconds. The skip is the explicit opt-in test requiring the user's previous real vector cache. One warning concerns the existing deprecated HTTP client alias in a test.
- Existing independent graph tests cover transaction failure, idempotence, namespace/version isolation and relationship/UNKNOWN round trips. Existing independent HTTP tests cover missing/expired/wrong-scope/wrong-audience tokens, host/origin rejection, redacted failures and lifecycle cleanup. They were included in the full run.
- New restore tests cover relative input configuration, copied-program queries with old source/data unavailable, artifact preservation, retained incompatible versions, config/model/program mismatch, bad checksum/artifact, legacy schema refusal, traversal/membership rejection and preservation of an existing destination.

Python 3.12.14, Neo4j Community 5.26.0, driver 5.26.0 and MCP SDK 1.30.0. The shared venv was explicitly linked for the registration test. The owned Neo4j service used a 384 MiB maximum heap and 128 MiB page cache and was stopped after each run. The final evidence-only commit must receive an exact-head regression/acceptance check before merge; the resulting full SHA and raw log hashes belong to the final evidence ledger, not an invented self-referencing SHA in this file.

## Actual Drive-to-Work acceptance

An offline build used the fixed **17-node/30-edge** source fixture. Deterministic synthetic document/query vectors were explicitly seeded to exercise dense/HNSW/exact/RRF mechanics. They are not Voyage output and provide no semantic-quality measurement. Paid requests: **0**.

Package: [batch2-small-graph-synthetic-e5b275ae.zip](https://drive.google.com/file/d/17O8q1y3khlRr_gk1B3Qdbucfjqa6P9wu/view). Size: **246,763 bytes**. Uploaded and downloaded SHA-256 both equal `587c2722cc3aec23000e45ebfae1d3163c0ed02ec473b034efc67d9cd3355809`. Indexed version: `20261028T085445-69d8bad94d`.

The original fixture source and index files were moved out of their original paths before restoration; no original user data was involved. The downloaded ZIP was restored into a separate directory. A new process imported `lct` from that restored directory, verified all index artifact hashes, and compared the complete raw graph, source Git metadata, version identities and UNKNOWN sites against the pre-backup snapshot. It compared BM25/dense/RRF results at module/class/function levels, HNSW against exact search, documentation BM25 and captured source retrieval with `live_file_matches=false`.

It then started the copied toolkit's real stdio MCP subprocess and called all **5** query tools. The preserved snapshot was reimported into an isolated namespace in real Neo4j; a loopback HTTP MCP server was started from the restored modules and all **4** read-only tools were called using the official SDK client. Node filters, raw nodes/relations, snapshot/source metadata and fingerprints matched. The HTTP verifier is explicitly test-only; this does not establish a public deployment or production OAuth service.

The first acceptance launch stopped before product restore because it required the original directories themselves to be absent. Work retained empty directory placeholders after the move. The reviewer corrected this harness condition to require the original **files** to be absent. No product behavior or expected retrieval result was loosened. Corrected restore and complete MCP acceptance both passed. The initial setup failure remains in raw evidence.

Reproduction utility: `tools/verify_portable_work.py` has `prepare`, `restore`, and `verify` phases; the restore phase consumes the normalized configuration from the checksummed package, so the old config file does not have to remain accessible. `verify` must run with an isolated Neo4j service and the documented `LCT_TEST_NEO4J_*` environment variables. All phases use explicit paths; no Drive secrets or access URLs are stored in the repository. Raw output, JUnit XML, transfer checksums, restore receipt and gate ledger are preserved in `LCT-Code-Indexes` on Drive.

## Decision and limits

**Third-round bounded code review and functional acceptance PASS**, subject to final-head evidence verification and unchanged merge target. RESTORE-001 is resolved; RETRO-001 remains resolved. The user authorized automatic merge after these gates pass.

This completes the small-graph Work workflow, not Batch 3. It does not prove fresh-machine dependency installation, Windows-to-Linux migration, real business data/vector migration, full-size performance or incremental graph updates. Schema-1 archives are not automatically migrated. Full-scale work must address the explicit 500-node/5000-edge Neo4j import bound and measure package/resource usage (some archive fingerprint paths still read the whole ZIP into memory). No paid Embedding authorization is inferred from the synthetic test.
