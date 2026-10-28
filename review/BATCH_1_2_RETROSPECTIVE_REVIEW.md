# Batch 1/2 retrospective verification, 2026-10-28

This supplements the original limited-scope review records; it does not erase them. Batch 1 is already merged at `3d06e10744d02fb5882d407aa1accd54dd62b848` on default branch `feat/local-code-tools-import`. Batch 2 initially had head `ae751dff3279a2bda76abfe2cbe032436c173f60` on `feat/neo4j-http-mcp-small-graph`; it is not merged. There is no assumed `main` branch. Root is the independent reviewer; GPT-6 SOL / medium performed the narrowly scoped test repair.

## Provenance and review rounds

The reviewer fetched current GitHub refs and complete recursive trees. All 85 Batch 1 and 89 Batch 2 non-report blobs matched Git blob SHA-1, including source, tests, dependency files and entry points. Local review directories are verified source snapshots, not clean Git clones. Comparing against pre-Batch-1 commit `7f3c2d025b972225367463a5cb619f2480905223` showed that the parser and eight failing tests were unchanged by either batch.

Original formal reviews: round 1 for each batch. This retrospective is round 2, not a restarted counter. Batch 1's small-graph implementation has no newly confirmed defect; its original commit does not have a green whole-repository test result. Batch 2 remains blocked by RESTORE-001 below. A future repair review is round 3; third-round failure or any confirmed P0/P1 requires human intervention under the agreed policy.

## Whole-repository baseline evidence

Command: run `python -m pytest -q tests` with JUnit output, using the owned Neo4j 5.26.0 service (384 MiB heap, 128 MiB page cache); driver 5.26.0, MCP SDK 1.30.0, Python 3.12.14. Services stopped after each run. Existing shared virtual environment was used; no clean-install claim.

| Exact starting head | Result | Duration |
| --- | --- | --- |
| Batch 1, `3d06e10744d02fb5882d407aa1accd54dd62b848` | 399 passed, 9 failed, 1 skipped | 19.03 s |
| Batch 2, `ae751dff3279a2bda76abfe2cbe032436c173f60` | 403 passed, 9 failed, 1 skipped | 20.59 s |

One failure was the registration test requiring `<repo>/.venv/bin/python`. The review directories used an external shared venv. Linking that actual environment into each snapshot fixed the setup; the registration test then independently passed in 0.33 s. This was an environment correction, not a product fix. The skip is the explicitly opt-in existing real-cache test. HTTP tests also report one SDK deprecated-client-alias warning.

RETRO-001 (P2, addressed in accompanying patch): eight old test cases had nine assertions requiring complete calls inside unmodeled With/AsyncWith protocols. Exact target sets remained correct. `EffectInventory.visit()` emits entry/exit `region` events; `event_coverage()` and the effect resolver reject unsupported protocol effects. The documented contract requires UNKNOWN_EFFECT / unsupported-protocol-region, propagating `unknown_origin=true`, `complete=false`. The patch changes only affected assertions and additionally checks their specific region receipts. It preserves factory creation-call completeness, exact targets, ownership and complex-generator uncertainty. No parser implementation or shared assertion defaults changed.

Developer verification of the patch: 54 targeted tests passed; full real-Neo4j suite 412 passed, 1 skipped. These are developer results, not independent post-push results. The final exact pushed SHA, independent rerun logs, hashes and gate ledger are recorded in the retrospective evidence archive in the authorized Drive folder `LCT-Code-Indexes`; do not infer post-push verification from this pre-publication report alone.

## RESTORE-001 — P2, confirmed, blocking Work portability acceptance

The user's selected mode is execution inside Work, with a package loaded from Drive in a new environment. Public HTTPS, an OAuth hosting provider and native ChatGPT plugin installation are not required gates for this mode. The old remote-deployment requirement in the historical Batch 2 report is superseded by this scope decision. Actual runtime startup, queries and clean-path restoration still need evidence.

Independent reproduction used only the existing 17-node/30-edge offline fixture and public build/backup/restore/query functions. `restore()` successfully extracted the validated archive into a different directory. After changing only config `data` to that restored data directory, BM25 query failed with `Index incompatible with program/config; rebuild before querying`. The original source/data still existed, so this failure is not caused by absent source files. See `restore-probe.log` in the evidence archive.

Root cause: `lct.common.identity()` hashes the absolute data directory as part of configuration identity; `lct.storage.manifest()` requires exact `config_hash` equality. `lct.management.restore()` extracts files but does not rebind runtime paths or establish validated relocation provenance. Keeping the old config would query the original data directory; changing it rejects the recovered index. Existing restore tests verify extraction/integrity but never query the relocated package.

Required bounded repair: implement explicit, checksum-verified relocation in the restore path, retaining source commit/node identities and every index artifact hash. Bind the restored configuration to the new data location and record the original and rebound identities. Keep ordinary query compatibility checks strict; do not globally bypass config/program checks, regenerate the graph, rewrite source versions, or call Embedding to conceal relocation failure. Evaluate source-path handling separately: absent live sources must use the captured source and report that fact. Do not claim full portability until the copied program itself queries the copied index after the original locations are unavailable.

Required regression/acceptance: changed data path with original path absent; node/edge/UNKNOWN/source-version equality; BM25 and source retrieval from the copied program; malformed/corrupt archive rejection; incompatible algorithm/model/program still rejected; actual Drive upload/download and hash equality; reimport into an isolated Neo4j namespace and MCP query after restore. Existing synthetic dense fixtures can test vector preservation without paid APIs. Full business indexing and scale acceptance remain Batch 3 work.

## Decision

No confirmed P0/P1. Keep Batch 2 unmerged and do not start Batch 3. Test alignment does not fix RESTORE-001. The next repair is specifically restoration/rebinding, followed by the remaining third formal review and required Drive-to-Work acceptance. No business repositories, full indexes, paid API calls or original data were changed in this retrospective.
