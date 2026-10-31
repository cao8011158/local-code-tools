# Partial analysis dependencies — independent review 1/3

Reviewed remote commit `358b63f4c07a8e847b74345eb1a214804e415e14`, parent `9dad3d1def60dc850dd379bbb61756fdd7c6c6c4`, tree `6dc999e3846145be5b19091efea8decec2a1baa1`. Branch: `feat/incremental-index-updates`. Root reviewed the sub-agent implementation and did not edit production code. The fixed review copy has 416 files verified against remote Git blob hashes; all non-review repository files are present. Unrelated historical review artifacts not available locally were not required or reconstructed.

## Decision

PASS for this limited persistence addition. No new production blocker confirmed. This does NOT complete Batch 4 or authorize merging it: coverage remains partial and the existing whole-capture simple-Python admission gate remains unchanged. This is not evidence of complete dependency tracing or business-scale local analysis.

## Source and lifecycle review

- `Analyzer.container_slots` records inspected writer scopes and a capture-wide future-writer subscription, even before an uncertain writer exists. Stable module identities are used. The shared 20,000-record budget stops only recording, marks truncation and does not stop graph analysis.
- `Graph.build` exports private records; `storage.build` removes them from public graph metadata; `split_graph` writes indexed SQLite tables and compact schema/count/partial/truncation metadata. This does not inflate ordinary status replies with dependency lists.
- `FileDependencies.analysis_readers` uses producer repository/path and kind; `analysis_watchers` uses kind/universe. Truncated records explicitly raise instead of returning a seemingly complete impact set.
- Full builds replace records; identical capture reuse preserves them. `merge_analysis_dependencies` fails closed for retained reads crossing a selected producer, retained global watchers, unavailable endpoints and budgets. It does not widen admission. Nonempty merge coverage is a helper test; the real certified local path currently exercises empty records.

## Independent checks and measured locality

Command in the fixed copy: `.venv/bin/python -m pytest -q -rs tests review/batch4-incremental/test_analysis_reads_independent.py review/batch4-incremental/test_container_scope_independent.py review/batch4-incremental/test_changed_python_independent.py review/batch4-incremental/test_module_lookup_keys_independent.py review/batch4-incremental/test_existing_package_context_independent.py`.

Initial result: **571 passed, 1 failed, 25 skipped in 31.58s**. All 557 repository tests passed. The one failure was in root's new test: after multiple publications it attempted to reopen a version correctly removed by default two-version retention. Original failure preserved in `analysis-read-independent-suite.log`. Root changed only that test to examine the retained previous publication, preserving the old-data-isolation assertion. Focused rerun: **3 passed in 1.08s**, command `.venv/bin/python -m pytest -q -s review/batch4-incremental/test_analysis_reads_independent.py`, log `analysis-read-independent-targeted.log`. These 3 overlap the original run; do not sum totals or describe the original full run as entirely green.

| Independent check | Result |
| --- | --- |
| Existing B subscription before A exists; add uncertain A with no ordinary graph edge | B already subscribed; new build records A→consumer B |
| Failed publication | Current pointer and old dependency records unchanged |
| Identical capture, then isolated A writer | Identical records preserved; new build removes obsolete read, keeps future watch; retained old snapshot unchanged |
| Recording budget reduced to 1 | Nodes, edges and full call-site records exactly match unrestricted analysis; dependency truncation explicit |
| Actual reverse API, 0 versus 40 unrelated modules | Two queries (target and foreign-repo negative control), one target row, 38 SQLite VM instructions in both cases |
| Actual SQL execution plan | Both queries use SEARCH USING COVERING INDEX analysis_read_producer; no SCAN |

The FileDependencies constructor still verifies the whole sidecar checksum once. Above locality counts measure actual indexed API queries after opening; they do not mislabel full integrity verification, initial builds, watch fan-out, or output serialization as constant work. A capture-wide watcher can legitimately select many consumers until a stronger exclusion proof exists.

25 skips: 24 require an owned Neo4j service, one requires optional existing real-cache input. No paid API, Neo4j service, full business graph, Drive or merge. Tests use actual offline public builds and SQLite. This addition does not alter MCP interfaces or their reply budgets.

## Remaining work

Other callback/name-resolution/Jedi analysis dependencies are not covered by these tables. Next work must establish which additional dependencies or conservative scopes are needed and make admission consume validated evidence before replacing the whole-capture syntax gate. Continue local-versus-full result comparisons; do not simply remove the current gate.
