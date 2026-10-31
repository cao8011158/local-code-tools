# Reviewer-owned historical expectation synchronization

The B1 closing commit is `b8eb6ab5aab4554a2b5fc90204d6c12a1c2655fb`.
Its original review tests and the original 69-failure developer log remain
available. Root owns these changes; the production developer did not edit
reviewer assertions. This is a pre-review record, not an acceptance verdict.

The public operation now parses changed Python files and selects downstream
execution owners. An unchanged downstream AST need not be parsed again. Old
`certified-simple-python-component` / `general-passive-component` mode and
whole-component parse-count assertions therefore cannot describe the new
route. Source membership changes, unresolved writer origins, or unavailable
candidate evidence can explicitly use a full build. Fallback work includes
the failed preflight and is not counted as successful local analysis.

| Tests | Updated checks; preserved controls |
| --- | --- |
| changed_python, crossrepo, relative_import, class_component | Actual changed-file parsing; explicit full reasons for unresolved effects/catalog changes; original fresh graph comparison and old-view checks retained. |
| dictionary_local, dictionary_flow, mixed_dictionary | Changed-file AST reuse, conservative unsupported-effect fallback, known-origin conditional update; all original fresh controls retained, including deletion and publication failure. |
| general_context, general_legacy_semantics | Membership and candidate changes use the current route; full context is already present during a full build; full private input/value/certificate comparison retained. |
| common_certificate, pure_validator | The current owner route replaces grammar admission; actual source comparisons, failure/retry and unchanged capture checks retained. |
| analysis_observations, analysis_inputs, scope_reads | Actual owner selection and changed-file parsing replace obsolete file-component helper hooks; positive/negative input persistence and full comparisons retained. |
| value_index, changed_python_access | The public update is traced through B1 `unit_container_readers` / `unit_readers`, with actual SQL plans, VM work, result counts and unrelated growth. Existing public value-query controls remain. |
| requester_access | Adding a Python provider changes membership and explicitly rebuilds; old requester methods are not falsely claimed to drive that route. Actual indexed requester API coverage remains in separate dependency-store tests, and this test retains fresh comparison. |

Root also added effect-receiver alias controls and open/closed-world
multi-pass returned-callback controls. `test_owner_update_independent.py`
compares public graph and private semantic tables, including all three B1
source tables, without discarding UNKNOWN, completeness or provenance.

Pre-review test-authoring mistakes are preserved in `root-batch2-history-sync1.log`
and `sync2.log`: a temporary local name shadowed an imported helper, and full
diagnostics omit a zero-reuse field. These are corrected in tests, not treated
as product defects. More importantly, executing the fresh controls exposed
stale candidate-input scopes and import-request ordering; those differences
remain blocking until the production merge is corrected and reverified.

The three product differences were repaired before candidate publication. The
updated 121 historical/new controls reached all their fresh comparisons: 119
passed initially; the remaining two needed retained_versions=4 to inspect the
first snapshot after three publications, then both passed. This retention test
correction does not alter production pruning. Formal fixed-remote validation
remains pending.
