# 4B pilot: captured source context and passive source reuse

Baseline: remote `feat/incremental-index-updates` `982db2d285fe371d3daf6a54b11934ea6ba6a314` (4A source fixed at `f80285978400be6e146e9d8bd8ab47c10a3416bd`). Development workspace is a nongit staging copy. This is the first 4B slice, not a certificate for complex business modules.

## Implemented boundary

The existing whole-capture v6 route remains first. If its predecessor is not v6 or its selected syntax is newly unsupported, a separate general preparation can retain only unchanged modules with `literal-functions-v1` source proof and empty old semantic facts. Every other current module is selected and reanalyzed. No retained passive proof means full fallback. Changed package initializers, ancestor layout, pin/config/runtime/document changes and new shadowing of the `re` or `dataclasses` helpers retain full fallback. A general candidate that becomes a closed all-v6 capture falls back to a full build, preserving the fresh certified candidate policy.

The passive source admits only module/function docstrings, uniquely named ordinary functions, `pass`, and primitive literal/None `return`; strict `_certify_v4` must also accept it. It rejects imports, assignments, classes, bases, annotations, decorators, defaults, starred signatures, lookups, calls, attributes, nesting and special/builtin helper names. The proof is a frozen source fact, not a claim that function definition has no binding event. The sidecar stores `(repository,path,raw sha256,policy)`; the manifest stores only schema/policy/count. Old captured source hashes, program/config/runtime/pin metadata and sidecar artifact digest are checked before reuse. Successful v6 local updates retain verified passive proofs and recertify selected source. Identical-capture reuse copies verified proofs.

General `Graph.build` receives all current Python source text and the complete current catalog, while AST scripts and site inventory are only for selected modules. A Jedi result for a captured module with no selected AST raises `RequiredAnalysisContext`; preparation adds that file and retries using a shared parse cache. No business source is executed. No fake provider AST is constructed. The full catalog output and immutable old-view publication rules remain.

For empty old facts, the candidate module/function catalog lookup uses `node_scope(repository,kind,path)` for each proof. Catalog non-CONTAINS edges and the existing sites/observations/import/analysis-input/value tables are each scanned once, marking only proof owners with records; an incoming edge marks its passive target. These fixed global evidence scans and full output materialization mean this pilot is **not** globally O(K). The per-proof catalog lookup does not repeatedly traverse unrelated nodes: `EXPLAIN QUERY PLAN` says `SEARCH nodes USING INDEX node_scope (repository=? AND kind=? AND path=?)`, with exactly 49 measured SQLite VM steps at 0, 20 and 100 unrelated same-repository modules.

## Actual source and oracle

The test copies unmodified fixed SM `a7b0804` `_execution.py` and `errors.py` bytes from the checked-in fixtures. A subsequent test copy changes `_execution`'s `"actor"` to `"actor_changed"`; another changes `errors`'s keyword-only `path` default from empty to `"root"`. With no passive file the update takes full fallback. With 20 unrelated passive modules it enters `general-passive-component`, parses only the two complex modules, reuses 20, and still exposes all 22 captured source files to Jedi. Nodes, edges, sites, query observations, import requests/dependencies, semantic reads/watches/input scopes and value-flow sidecar tables match a fresh full build. The original snapshot remains unchanged after update.

Explicit synthetic append-only imports of `noise_7` into original `_execution.py` are labeled synthetic: a new `from noise_7 import pure_7` call and a previously present incoming provider both select/parse that passive source, retain the other 19, and match the full oracle. Deletion of one unrelated passive file retains 19; failure before publish leaves the old view intact and retry succeeds. Same-capture reuse preserves the proof. A v6 full → v6 local → insertion of the original two complex files retains all passive proofs, then general updates only the two complex files and matches fresh full. Converting the remaining complex files to ordinary literal functions takes a full v6 rebuild so the oracle uses the same candidate policy.

## Test evidence and limits

The prechange test log `general-passive-prechange.log` records that a 20-noise complex capture was full; a 0-noise full fallback is intentionally allowed. Iterative failed diagnostics remain in `general-passive-first.log`, `second.log`, `third.log`, `general-passive-import.log`, `general-passive-targeted4.log`, and the earlier `general-passive-final-fast.log`; the last showed two historical mode expectations requiring the new shadow gate and narrow class test update, not a demonstrated semantic mismatch. The final focused run `general-passive-targeted-final.log` reports **19 passed in 7.29s**. The previous related run `general-passive-related.log` reported **53 passed in 9.39s**. The final post-fix full suite is recorded separately in `general-passive-final-fast-fixed.log`.

The final post-fix full suite reports **647 passed, 27 skipped in 39.51s**. Python syntax compilation succeeded earlier in development. The focused SQLite index experiment returned the same single target and 49 VM steps for 0/20/100 unrelated modules; its plan used the exact `(repository,kind,path)` search. All fixture builds were offline and lexical-only.

This pilot does not prove reuse of any of the six complex related business files; they remain selected if captured and general preparation can therefore cost a full complex analysis. The `analysis_inputs` scope coverage remains partial; no new complete read witness is claimed. External dynamic imports that Jedi cannot resolve retain their real unknown result. Package layout and unavailable captured providers remain conservative boundaries. The ordinary full public graph/materialization cost remains proportional to total output even when AST analysis is local. No API, service, installation, business code execution, or whole business graph was used.

## Changed file whitelist

Production: `lct/passive_python.py` (new), `lct/python_analysis.py`, `lct/graph.py`, `lct/python_incremental.py`, `lct/storage.py`. Tests: `tests/test_general_passive_incremental.py` (new), `tests/test_changed_python_gate.py` (one historical expectation plus fresh all-table oracle). Documentation: `docs/INCREMENTAL_UPDATE.md` and this report/logs. No edits to `STAGE_REPORT.md`, retained early drafts, or parent independent tests; no push or merge.

Final source SHA-256 and changed-line totals against the frozen 4A copy:

| File | + / - | SHA-256 |
| --- | ---: | --- |
| `lct/passive_python.py` | 36 / 0 | `eb7f1e8c6b3f83988957b12a1af0229984174a21894746c721eb176ca1e40205` |
| `lct/python_analysis.py` | 23 / 4 | `c23a4268898dcef5677bfe25852ac285d7fbd319273d5da8f323b2ddb3b94c1f` |
| `lct/graph.py` | 2 / 2 | `d7df3d5a541ba21ed1aae4497b50211b5303d24aa576d6489146df00ebe8e2fc` |
| `lct/python_incremental.py` | 127 / 25 | `544b2c23c7cd41471cd07e22e46b63460784ff0be212975dbe8613487f0b15ea` |
| `lct/storage.py` | 57 / 5 | `c51d7711a4cc98a8f8c3f9fcb08a760c28dcdb06e98517ca98520472587caf1c` |
| `tests/test_general_passive_incremental.py` | 278 / 0 | `6969bc9115c515082647e1af4ede68d98469aa36bec6fe218ee1517edc018fca` |
| `tests/test_changed_python_gate.py` | 9 / 5 | `c62d0e5b1f3189c49e22963e22d053554978b84dbe17d8f7f7726ffb253ec0ad` |
| `docs/INCREMENTAL_UPDATE.md` | 16 / 0 | `f89c30aed690702a87e6fdbf6d2bc70a22e0de1efa205ad9575b01dc3fda062b` |
