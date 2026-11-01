# LO-2 developer handoff — local-only warm graph updates

## Change and scope

- Warm `storage.build` uses immutable prior graph evidence for owner selection. Identical Python capture reuses the graph; any other warm capture calls `unit_incremental.prepare`. It never routes a normal warm update to `Graph.build(selected_owners=None)` or the legacy general/strict Python fallback. An incompatible schema, runtime, program/configuration, repository/pin policy or corrupt artifact fails with `ToolError` before candidate publication. Ordinary revision, cleanliness and source membership changes enter local selection.
- The public cold builder explicitly seeds all new AST definitions into `Graph.build(selected_owners=set(asts))`; this uses the existing conservative candidate index and computes the full initial value-flow sidecar. Transient read witnesses are removed from the cold manifest. Cold indexing still captures and analyzes the full source inventory.
- Selection parses only changed/new Python files, retains unchanged cached ASTs, and replaces observations of affected owners. Deleted owners and their sites, edges, queries and source observations are removed. Old edges into changed/deleted producers select source owners before merge. Indexed source readers, exact container-origin subscribers, owner-specific analysis watches/reads, import requesters and negative lookup keys expand the closure. Added package ancestors/reexports and dirty/clean pinned binding changes select their actual import requesters. Unknown writer origins use owner-specific universe subscribers; a budget-limited old snapshot also follows providing-module reads and the writer's captured import namespaces when early analysis omitted a container subscription.
- Existing positive value-flow read witnesses remain usable under partial coverage and are revalidated with the current flow. The `analysis_limited` flag persists across local reuse. `UNKNOWN`, open receiver sites, opaque effects, class/header changes and a limited association budget no longer trigger automatic full analysis. Semantic graph/source facts are compared with the LO-1 oracle in synthetic and real-source tests; execution-read/watch records are exercised by functional invalidation tests.
- `python_analysis` canonically orders transitive coverage receipts that previously depended on process-local AST set iteration. This changes incidental receipt ordering only.

## Failure reason disposition

| Prior reason/gate | LO-2 outcome |
| --- | --- |
| Python/document membership, package initializer, no Python source change | Local changed-file/catalog/negative-import selection; document-only update selects zero Python owners. |
| Changed owner/header, opaque effect, unresolved prospective writer, open receiver | Reanalyze changed owners; widen through recorded owner-specific watches, container origins, import/read paths. Keep unresolved `UNKNOWN`. |
| Previous/current analysis limited, combined association count, partial value-flow coverage | Admit and preserve limited/partial declarations; reuse positive witnesses and recompute selected closure. A genuinely truncated dependency ledger is still an explicit error. |
| Changed cross-repository binding | Compare old/new binding outcomes and use indexed `import_lookup_keys` by source repository and module range; select matching requesters. |
| Invalid prior artifact/schema/program/config/query runtime or incompatible repository/pin policy | Explicit `ToolError`; no publication and old current pointer preserved. |
| Failed proof/rebind, impossible convergence, missing necessary analysis context, truncated combined dependency ledger | Explicit reason and `ToolError` without full fallback. These guards remain for evidence that cannot safely support local publication; future acceptance may require more local widening. |

## Locality and limitations

The AST effect catalog prepares a writer-scope index from cached ASTs on each analyzer creation. It is metadata/index preparation over all cached scopes, measured separately from selected owner query/association work; unrelated sibling functions are not selected for unknown-writer subscribers. Full inventory/hash, snapshot serialization, and fresh test oracles also have global input cost. The full 83-file source acceptance and measured unrelated-growth budget belong to LO-3. This handoff makes no claim that every possible Python construct has complete local evidence: explicit evidence errors preserve the old current version. No Jedi/Parso replacement, business-code execution, external embedding provider, Neo4j process, or dependency upgrade occurred.

## Files

Production: `lct/storage.py`, `lct/unit_incremental.py`, `lct/graph.py`, `lct/python_analysis.py`. Documentation: `docs/INCREMENTAL_UPDATE.md`, `docs/FUNCTION_VALUE_DEPENDENCIES.md`, `.agents/skills/code-graph-dependency-change/SKILL.md`. Tests: `tests/test_local_only_update_policy.py`, and updated actual-item, analysis sidecar/input, Batch 3 acceptance, changed-Python, class/common certificate, container-slot, cross-repository, dictionary-flow, general/passive, query reuse, mixed-dictionary, owner, relative import, and source-prepare test modules. Root owns `review/local-only-updates/test_local_only_flow_independent.py`, the cumulative `review/batch4-incremental/STAGE_REPORT.md`, and remote publication/review; their working-tree presence is not a developer edit.

## Checks

| Exact command | Result | Saved log |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q tests/test_python_pipeline.py tests/test_python_call_access.py tests/test_python_review_regressions.py tests/test_python_review_round3.py tests/test_dictionary_value_flow.py review/local-only-updates/test_local_only_flow_independent.py tests/test_local_only_update_policy.py --tb=short` | 254 passed in 16.73s. Initial cold attempt failed on missing transient witnesses; second failed on tuple-keyed witness serialization; both logs retained and fixes included. | `lo2-cold-frontend-final2.log`; prior `lo2-cold-frontend-target.log`, `lo2-cold-frontend-final.log`. |
| `.venv/bin/python -m pytest -q review/local-only-updates/test_local_only_flow_independent.py tests/test_local_only_update_policy.py --tb=short` | 19 passed before public cold-path change; same cases included in the 254-pass final focused command. | `lo2-target-current.log`. |
| `.venv/bin/pytest -q tests --deselect tests/test_batch3_actual_acceptance.py::test_nine_original_bytes_limited_graph_bm25_and_attached_real_usearch --tb=short` | 699 passed, 27 skipped, 1 deselected in 100.69s; exit 0. | `lo2-fast-main-final.log`. |
| `git diff --check` | Passed. | Command output empty. |

Earlier red preflight and main-suite logs remain unchanged in this directory. The expensive nine-file real-source group is the specified fast-suite deselection; full 83-file public entry acceptance remains LO-3.
