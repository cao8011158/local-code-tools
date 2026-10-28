# Batch 3 — full business graph and retrieval indexes

Status: implementation/preflight in progress; formal reviews completed: 0 of 3. No merge or full-scale acceptance claimed.

Tool base and merge target: `655b78a834c40542bf62c09bdd508c17d7f46450`, default branch `feat/local-code-tools-import`. Working branch: `feat/full-business-graph-indexes`.

Frozen source heads:
- agentic-trpg: ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436
- trpg-state-machine: 4166e52f0809ae80ba1694295bb0739acec76bd8
- trpg-rules-engine: ab276fffc5ff02a973e1c767543e712dd0897451

User authorized continuing Batch 3, GPT-6 SOL/medium developer subagents, independent pushed-code review, automatic merge only after all gates. Confirmed P0/P1 stops for human; third failed review stops. The supplied temporary Voyage credential is outside the repository and must never enter reports, artifacts or Drive. Connectivity was verified without authentication. New paid requests remain pending an explicit bounded run budget after a concrete input estimate.

Workstreams:
1. Read-only source acquisition: select current configured Python/Markdown roots, fetch pinned GitHub blobs and verify their Git blob SHA and SHA256. Reuse byte-identical local captures. Record exact selected scope and omissions. Captures are NOT Git checkouts; never fabricate Git HEAD.
2. Explicit verified source-snapshot inventory mode, preserving ordinary Git input and rejecting source/config drift. This allows actual source commit provenance without a fake local Git repository.
3. Bounded Neo4j bulk import replacing per-record writes, with fixed identifier whitelists, atomic publication/rollback, immutable namespace/version identity and unchanged read caps.
4. Real-scope graph/BM25 build and estimate; then authorized Voyage vectors for module/class/function inputs, existing HNSW/RRF retrieval, package/restore and independent real-data/scale acceptance. Existing docstrings supply summaries; no LLM-generated summaries or paid LLM calls.

Initial source scope from pinned tree inventory: 445 Python/Markdown files, 7,295,748 bytes; 286 Python files. These are scope counts, not built graph/vector counts. Omitted tests and non-Python files must be explicit. Full business-index publication remains gated on real runtime evidence, not synthetic-only tests.

Testing: development targeted tests; combined fast full regression and existing independent counterexamples before push/review; real Neo4j scale, rollback and namespace tests; source-snapshot drift tests; eventual actual Drive upload/download/restore with raw identity checks. Shared environment must not be described as a fresh-machine installation. Preserve raw logs/JUnit and actual commit/hash bindings. No API costs or success claims inferred from credentials alone.
