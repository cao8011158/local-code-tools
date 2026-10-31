# Owner update independent checks (in progress)

Remote implementation baseline: `4537843aac065c5d869250f0026f6f00470f1c7e`.
Root owns `test_owner_update_independent.py`; the developer may execute it but does not edit its assertions.

The public `storage.build()` checks cover changed caller actual arguments, multiple callers, functions passed through returned values and multiple forwarders, dictionary values, future/deleted import providers, publication failure, and true unrelated functions containing real calls. The oracle compares all public graph records plus analysis reads/input scopes/value records and the new owner dependency tables. It does not strip UNKNOWN, completeness, provenance or version fields. Incremental scheduling diagnostics and AST-cache bytes are separate from semantic records.

The locality control uses real production reverse-lookup functions with 0/20/100 unrelated owner and name rows. Both SQL plans must use SEARCH through an index and never SCAN. VM work may differ by one EOF/next-key boundary check between a one-row and a larger index; the 20/100 results must remain identical. Draft measurement was 27/28/28 instructions; this is not a claim that the whole update is O(K). Capture, AST context preparation, snapshot validation, cache serialization and output materialization remain separately visible costs.

Frozen old production baseline, separately archived before development:

- `pytest -q tests --tb=short`: 647 passed, 27 skipped, 41.72s.
- Broad historical `tests` plus `review/batch4-incremental/test_*.py`: 806 passed, 32 skipped, 11 failed, 71.53s. Five failures are the new root capability assertions against the old implementation (complex callback/return/dictionary cases still full rebuild). Six pre-existing failures are obsolete historical assertions or an unavailable external service: `test_actual_source_controls_independent.py` expects old full mode; both actual-source diagnostic files expect the old None certificate; `test_module_lookup_keys_independent.py` has two obsolete full-mode assertions; `test_lookup_neo4j_independent.py` requires LCT_TEST_NEO4J_URI. These historical records are not rewritten to manufacture a clean baseline. The new root test was included by explicit shell expansion despite the --ignore flag; the counts here include that fact.
- The first new-test baseline run had a root query interceptor missing the `goto` keyword. The interceptor was fixed, the initial log preserved, and the corrected six-case baseline produced 5 capability failures / 1 pass in 2.08s. Those are mode failures, not five proven semantic corruption bugs.

Further development and fixed-candidate independent results will be appended after completion; draft runs are not a formal review verdict.
