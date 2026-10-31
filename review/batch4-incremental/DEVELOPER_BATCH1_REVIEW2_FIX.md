# Batch 1 review round 2: unknown argument support

Issue `B4-SRC-01-UNKNOWN-ARG` (P2) is fixed in `Analyzer.parameter`. The existing `argument-unpacking` and `missing-required-argument` branches still return their original `UNKNOWN` result. When the callee, providing call site and formal callback consumer are known, they now additionally record an `actual-parameter` support: provider owner and actual call-site ID; consumer owner and actual consuming callback site; parameter name/index/kind; `argument_source.kind` `unpacking` or `missing`; empty target IDs and the original unknown reason. No unpacking inference, call target or completeness logic changed.

Verification:

- Root independent unknown input controls (3), root Batch 1 source controls (11), developer controls (6): 20 passed.
- Combined main and historical suite: **825 passed, 32 skipped in 77.27 seconds**; raw log `developer-batch1-review2-regression.log`. Same exclusions as the Batch 1 developer handoff (six pre-existing diagnostic failures and the future Batch 2 owner update controls).
- Fresh graph call-site JSON for `execute(*values)`, `execute(**values)`, and `execute()` was compared byte-for-byte against the fixed baseline source. `cmp` passed for all three. Reproduction script and both raw JSON payloads are `developer-batch1-review2-oracle.py`, `developer-batch1-review2-baseline-sites.json`, and `developer-batch1-review2-current-sites.json`.
- `ruff check` on the four production modules and developer test with `--select F,E9`: passed.

The origin evidence remains partial and does not authorize selective owner recomputation. The public build route remains the Batch 1 baseline route. No push or merge.
