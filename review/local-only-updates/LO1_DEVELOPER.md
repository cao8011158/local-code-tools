# LO-1 developer result — semantic oracle comparison

## Scope and baseline

- Implementation baseline: local materialization `141e575a546ee7976aa002e2502ec1dae86b7de3`; remote target `e3db45fcf1362f0a26e0ab7760b12b4fd408ce64`, tree `303b53c85330c98897d7fc46ea02731b373f81fa`; branch `feat/local-only-updates`, target `feat/local-code-tools-import`. This work is uncommitted and unpushed. Root owns independent review and cumulative stage report.
- LO-1 changes only acceptance comparison and the applicable contract/documentation. No production scheduler or analyzer changes. Full six-file fixture source is captured and never executed.

## Change

- `tests/semantic_comparison.py` compares all graph/source tables and metadata, retaining node/edge identity, sites and targets, UNKNOWN, completeness, decisions, boundaries, Jedi definition evidence, source supports, container subscriptions/writes and value provenance. It removes only LCT candidate traversal steps and collapses repeated *identical* write-source diagnostic gap records in both the site decision and copied LCT evidence decision, including nested transitive coverage receipts; distinct reason/location records survive. Auxiliary owner execution reads, watches and input events are excluded from raw oracle equality. They remain required for functional invalidation tests in LO-2.
- `tests/test_batch3_actual_acceptance.py` uses this comparator for the six-file scenario, retains exact comparison for three/nine cases, and explicitly checks real six-file source-support/subscription/write table equality. Rejected `StateMachineError` constructor candidates encountered in full analysis explain extra Jedi execution reads; those reads are a record of visited candidates, not independently validated source support edges.
- `tests/test_semantic_comparison.py` tests allowed trace/repetition differences and rejection of changed target, graph identity, source support/subscription/write, value read, UNKNOWN, completeness, selected target, boundary, Jedi evidence, distinct gap reason/location and source location.
- Contract and local procedure distinguish currently shipped full fallback (documented as historical Batch 3 behavior) from user-authorized LOCAL-ONLY-UPDATES policy pending LO-2.

## Checks

| Command | Result | Log |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q tests/test_semantic_comparison.py review/local-only-updates/test_semantic_contract_independent.py tests/test_batch3_actual_acceptance.py::test_complex_seed_group_missing_external_context_and_fresh_update --tb=short` | 29 passed, 22.57s after transitive receipt fix. Independent preflights first found a copied nested receipt mismatch (6 passed/1 failed) and then transitive dependency receipt mismatch (7 passed/1 failed); targeted normalization fixed both. | `lo1-target-final.log`; earlier `lo1-target.log`, root-owned `lo1-root-preflight.log`, `lo1-root-transitive-preflight.log` retained. |
| `.venv/bin/pytest -q tests --deselect tests/test_batch3_actual_acceptance.py::test_nine_original_bytes_limited_graph_bm25_and_attached_real_usearch --tb=short` | Final clean run: 697 passed, 27 skipped, 1 deselected in 118.03s, exit 0. Earlier runs with prior helper revisions also passed, but do not substitute for this final run. | `lo1-fast-main-final.log`; prior `lo1-fast-main.log` retained. |
| `git diff --check` | Passed. | Command output empty. |

## Boundaries for LO-2

The comparator is an oracle, not a scheduler certificate. Functional invalidation tests must show owner execution-read/watch/input ledgers continue to capture actual dependencies even when rejected candidate traversal differs. Ordinary updates must not use automatic full fallback or hidden all-owner work; UNKNOWN by itself is admissible. Corrupt/incompatible cache may fail before publication, preserving current. Full fresh builds are test oracles only. Real full-source scale and untouched-owner counts remain LO-3 acceptance work.
