# Batch 1 developer handoff: observed source origins

Scope: source evidence only. The public `storage.build` strict/general incremental routes remain as before; owner scheduling is not enabled. Paused owner scheduler, AST cache and owner tests remain only in the root's pre-approved-batches checkpoint. This work is not pushed or merged.

## Source observations

- `Graph.build` attaches ordinary call-target support to the actual source definition and consumer call site.
- `Analyzer.parameter` captures actual positional/keyword argument sources and definition-time defaults only when the parameter is resolved at a consuming site. Each parameter/consumer site has a separate row. `Analyzer._resolve` records returned value sources.
- `Analyzer.container_slots/subscript` records dictionary literal and matched assignment/deletion/augmented-assignment writers and concrete or range readers. Existing `Atom.allocation` differentiates unique instance containers. Resolution memo hits replay actual container reads for every final consumer.
- SQLite `unit_source_supports`, `unit_container_subscriptions`, and `unit_container_writes` have producer/consumer and origin indexes. Full/identical captures preserve sources; changed-Python legacy local routes declare unavailable instead of publishing a partial ledger as reusable. Budget truncation is explicit.
- `FileDependencies.unit_sources` pages inspected evidence with a byte budget checked using indexed IDs and SQLite blob byte lengths before reading payload. `unit_readers` and `unit_container_readers` return complete indexed reverse lookup results. The latter keeps all readers of one origin across keys, with an explanatory key relation. Exact-key write lookup is for inspection; broad writer discovery uses origin without a key.

Coverage remains `observed-source-supports-partial`: unknown and candidate statuses are retained. It is not a complete Jedi/candidate input witness, and does not authorize selective recomputation. Public graph semantics and precision are unchanged.

## Verification

- Developer test `tests/test_dependency_origins.py` and root-owned independent test `review/batch4-incremental/test_dependency_origins_independent.py` cover distinct callback sites, defaults, ordinary calls, missing/dynamic/None/numeric keys, separate containers and allocations, memoized getters, identical reuse, old schema, pagination, budget, and indexed locality.
- The static combined run passed **822 tests, 32 skipped in 78.52 seconds**; raw output is `developer-batch1-regression.log`. Historical diagnostics with known frozen-baseline failures and Batch 2 owner scheduling controls were excluded; see the command below. The first attempted historical run overlapped a production edit and was invalidated by `program_hash` compatibility. The later static run is the evidence.

Command:

```bash
mapfile -t batch1_review_tests < <(rg --files review/batch4-incremental | rg '/test_.*\.py$' | rg -v 'test_owner_update_independent|test_actual_source_controls_independent|test_actual_source_current_diagnostic|test_actual_source_subset_diagnostic|test_module_lookup_keys_independent|test_lookup_neo4j_independent')
.venv/bin/python -m pytest -q tests "${batch1_review_tests[@]}"
```

## Batch 2 boundary

The origin sidecar is incomplete as a global dependency proof. A future scheduler must combine it with existing CALLS, import/parameter/effect ledgers and conservative unknown-input guards. Source `container-writer` rows identify candidate support, not runtime execution order. Consumers of newly added writes can be found by the old same-origin subscription index; no old support edge is required.
