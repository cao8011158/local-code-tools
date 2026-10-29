# Batch 3 — full business graph and retrieval indexes

Status: staged-import repair passed independent review; formal reviews completed: 2 of 3. No merge or full-scale acceptance claimed. Earlier task text below records the initial plan; the appended continuation supersedes its one-transaction rollback design.

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

## Authorized continuation: staged import (2026-10-29)

User discussed and then instructed continuing with per-batch commits, incomplete-version isolation, final content verification and atomic publication. Source base is 56a04275bc72c982559e1b47b82af541d10dd40d on the existing branch; merge target remains 655b78a834c40542bf62c09bdd508c17d7f46450. Formal review count remains 1/3; this is not a new counter.

Scope: importer and its compatibility readback, bounded graph/source evidence chunks, DB-enforced writer ownership/fencing, failure cleanup/retry, relevant tests and contracts. Same-content complete scopes skip write preparation. Failed imports may retain unpublished data; ordinary reads must reject it. Retry may clean and restart (not promise checkpoint resume). Existing complete versions and full snapshot_info shape remain usable. The separate Batch 2 MCP startup fingerprint-only fix remains paused; this instruction is not recorded as an explicit waiver for a fourth Batch 2 review.

Use GPT-6 SOL / medium developer; root independent review after push. Start with small/synthetic fixtures and fault injection, then fast regression and a bounded native Neo4j memory check. Do not rebuild business graph or call Voyage in this repair. The prior real graph at /tmp/lct-b3-locality-fixed-20261028 is no longer present after environment refresh. Source revisions and evidence survive in GitHub; regenerate only after prerequisites pass, and persist the expensive result before downstream tests.

## B3-004 reopening completed (2026-10-29)

User approved continuing the explained narrow startup repair. Implementation caa9d1ee6c54187580061eb90932e72d578e83e4 passed one authorized additional Batch2 review after prior3/3; do not reset history. B3-004 closed. Batch3 remains2/3. Native full regression462 passed/1 skipped. Identity/general provider migration and automated retention remain outside this repair. Earlier pause wording above is historical and superseded for B3-004 only.
