# B4-SOURCES independent review, round 1/3

Verdict: changes required. Fixed commit `948eea8a303a4b6cb35db483e06480e115dbfaa3`, tree `ebbd49a614d0e3330d2c666b040867ac0df9c590`; complete batch diff from `60784b413d6f9133e5ac1344ccd0bd232e78abe4`.

Root verified 289 materialized files against remote Git blob IDs, zero mismatches. One old local developer log is not a remote review file. Future owner scheduler/AST-cache drafts are absent from the remote tree and fixed review directory. Production implementation was written by the developer; root wrote independent checks and reports.

## Independent results

- Fixed-candidate main plus applicable historical checks: **822 passed, 32 skipped, 77.62s**, exit 0. This includes the 11 root source checks and 6 developer checks; do not add their counts again. Six previously failing historical diagnostic/service items and future Batch 2 controls remain excluded as documented in the developer report.
- Reproducible six-file old/full semantic comparison: all 16 legacy table hashes and metadata equal the original production baseline `4537843`; 18 nodes, 57 edges, 11 call sites. No UNKNOWN, provenance, identity or completeness fields were removed from the comparison.
- Source queries execute four SQL statements and return two supports, one reader and one subscription. VM steps at 0/20/100 unrelated containers are cold 161/162/162 and warm 157/158/158; actual statement plans use SEARCH indexes and no SCAN. Snapshot-constructor integrity checks and complete capture/serialization costs are separate, not an O(K) whole-update claim.
- Production and new tests/reproducer pass F/E9 static checking. The developer-only unused import cleanup changed no production code or assertions.
- Additional review probes for `*values` and `**values`: **2 failed in 0.53s**, both because a known providing call has no saved source relationship, despite the analyzer already finding the caller and preserving UNKNOWN in the public call result.

## B4-SRC-01-UNKNOWN-ARG — confirmed P2, open/blocking

Ownership: introduced in this Batch 1 source-observation implementation. The old public full-analysis behavior is unchanged; the new ledger is partial and not yet used for selective updates. This is an incomplete newly promised dependency record, not a confirmed existing public graph corruption or P1.

Trigger: `provider.provide(values)` calls captured `worker.execute(*values)` or `execute(**values)`, and `execute(callback)` consumes `callback()`.

Expected: even though the argument value/binding is unknown, the providing owner/call site and consuming owner/site are known. Save an `actual-parameter` support with unknown status, formal parameter identity and the `argument-unpacking` reason; indexed `unit_readers(provider.provide)` must include `worker.execute` at its callback site.

Actual: `Analyzer.parameter` appends `unknown('argument-unpacking')` and bypasses `_unit_support`, which only runs in the successfully resolved actual/default branches. `unit_sources` has no actual-parameter rows, and the providing owner cannot find the consuming function through this new relationship. The missing-required-argument branch has the same omission shape: the additional three-variant control (*args, **kwargs, and missing required input) produced 3 failed/0.54s; its original command duration is retained in source-origins-unknown-variants-review.log.

Required repair: record the known providing/consuming locations on these unresolved binding branches, with empty/unknown candidate values as appropriate and accurate reasons. Preserve the original UNKNOWN result and all existing analyzer behavior. Do not implement argument-unpacking evaluation, remove guards, invent a concrete function target, or relabel coverage complete. Add the missing-required-input variant; rerun the source controls, original public semantic oracle and required full regression.

The next formal review is round 2/3 for this same chain. Batch 2 remains blocked pending Batch 1 acceptance; no merge.

## Round 2/3 — pass

Fixed `d2ac250bd4f6563415a7a77a6645d47e7154a7e9`, tree `c7b0bdcf3b8a3f1082d89119db3acd0fe8168880`. The only production repair after round 1 is source observation in the existing unpacking/missing-required UNKNOWN branches. The full batch remains based on `60784b413d6f9133e5ac1344ccd0bd232e78abe4`.

- **B4-SRC-01-UNKNOWN-ARG resolved.** All three independent variants now save the known provider/call site and consuming formal site as unknown actual-parameter support, with accurate original reasons and no invented target IDs. The reverse reader index finds the consumer.
- Independent fixed-candidate full required suite: **825 passed, 32 skipped, 74.96s**, exit 0. The 3 regression variants, original 11 root controls and 6 developer controls are included, not added as separate coverage.
- 302 materialized remote blobs matched, no mismatch. One old developer log is outside the remote candidate; inactive scheduler/AST-cache draft files are excluded. No production files changed during review.
- The developer also reran the exact fixed directory without the inactive orphan draft: targeted **20 passed/3.46s**, main **653 passed/27 skipped/41.53s**. Commands and hashed raw logs are bound in BATCH1_EVIDENCE.json.
- Root independently regenerated original and repaired full site JSON for unpacking and missing input: byte-for-byte equal in all three cases. The six-file, 16-table legacy semantic comparison and metadata are also equal to original `4537843`. F/E9 passes.
- Root repeated the actual source lookup growth control on this head. Cold/hot 0/20/100 SQL and output counts remain constant; VM steps preserve the same fixed boundary/prepared-statement differences. Actual SELECT plans remain indexed SEARCH without SCAN. Snapshot hashing, full source preparation and materialization are explicitly outside that query-only measurement.
- The evidence checker is READY with two preserved review rounds and no unresolved findings, at observed code head d2ac250 and unchanged target fc857f3. READY applies to Batch 1 only; the entire feature cannot merge before B4-OWNER-UPDATE and B4-ACCEPTANCE.

The new origin ledger is deliberately observed/partial. It complements existing semantic-input and import evidence; it must not be treated as an exhaustive negative dependency proof in Batch 2. The public incremental route is still the old route until that batch. No paid API, business-source execution, external service startup or merge was performed.
