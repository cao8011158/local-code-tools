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
