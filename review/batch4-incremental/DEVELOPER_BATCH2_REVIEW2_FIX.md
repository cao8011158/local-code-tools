# B2 review 2 candidate: selected open receiver coverage

This repairs B4-OWN-04, discovered during the bounded Batch 3 real-source
acceptance. It changes only B2 owner admission, its public explanation, and
project developer controls. It does not change the full analyzer, Jedi,
association budget, UNKNOWN semantics, or source-origin precision.

## Reproduced defect and decision

Fixed SM commit `a7b0804d5635e185a79ff3c1d1fa6241c2b858fe` supplied
`combat.py`, `dnd_runtime.py`, `item_package.py`, `availability.py`,
`errors.py`, and `item_units.py`, each copied as its exact existing fixture
bytes. After a comment-only update in `dnd_runtime.py`, changing the actual
`item_units.py` limit `2**63 - 1` to `2**62 - 1` selected the
`availability.query_action_availability` owner. Its targetless
`self._combat.query_action_availability` site retained
`open-receiver-input`, `UNKNOWN`, and incomplete
`instance-field-coverage`. Owner output had 44 association trace steps and
122 coverage gaps versus fresh full's 100 steps and 1134 gaps; the old/new
unit input event sets differed. Graph edges and targets matched, but
provenance and input facts did not. The fixed original full analyzer's fresh
result also had 100 steps/1134 gaps; this was introduced by B2 owner
selection, not a change to full-analysis accuracy.

The scheduler now indexes old sites with that exact opaque receipt once by
execution owner. It falls back to full when one such owner is actually
selected. The same predicate checks new sites produced by selected analysis
and preserves preflight work metrics. The predicate requires the actual
`open-receiver-input` reason, no concrete targets or boundaries, and
`write_source_coverage.rule=instance-field-coverage` with incomplete
coverage. A different open receiver may have
`write_source_coverage=None` (e.g. `self()`); it is not a field receipt
and cannot be dereferenced as a dictionary. Ordinary unknown callbacks and
unselected opaque owners do not become a global syntax gate.

The first independent negative control wrongly called `Opaque.ignored(self)`
unrelated to a changed caller: its old exact owner ledger contained a real
`parameter-origin` read from that caller module. Root retained that red
diagnostic, replaced the unrelated control with an actually unreferenced
`idle.py` edit, and separately asserts the old read relation. The guard
does not suppress or rewrite that observed dependency.

## Static developer verification

Commands ran after the final code/test edit and exclude the unfinished B3
acceptance checkpoint:

- `.venv/bin/pytest -q tests > review/batch4-incremental/developer-batch2-review2-final-main.log 2>&1`: **675 passed, 27 skipped**.
- `.venv/bin/pytest -q tests/test_owner_incremental.py tests/test_dependency_origins.py review/batch4-incremental/test_owner_update_independent.py review/batch4-incremental/test_owner_effect_origins_independent.py review/batch4-incremental/test_owner_candidates_independent.py review/batch4-incremental/test_owner_auxiliary_edges_independent.py review/batch4-incremental/test_owner_receiver_coverage_independent.py review/batch4-incremental/test_dependency_origins_independent.py review/batch4-incremental/test_source_origin_unknown_inputs_independent.py > review/batch4-incremental/developer-batch2-review2-final-targeted.log 2>&1`: **67 passed**.
- `.venv/bin/ruff check lct/unit_incremental.py tests/test_owner_incremental.py --select F,E9`: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed.

The project regression compares the actual six-file change to a fresh full
build across 20 private/public semantic tables. A second regression uses an
actual targetless `self()` site with `write_source_coverage=None`; its
unrelated idle update remains an owner update and matches fresh sites.
The independent receiver control file now has four passing cases, including
the corrected unrelated owner and documented parameter-origin case.

## Handoff and boundary

The B2 review 1 fixed commit was `4f73d150cd4831f29d042b4eb692ea845a6b64ce`.
The review 2 delta is `lct/unit_incremental.py`,
`docs/INCREMENTAL_UPDATE.md`, and `tests/test_owner_incremental.py`;
root-owned review tests and cumulative report are excluded. The unfinished
B3 test was moved to
`/workspace/scratch/45363df3617b/task-evidence/b3-acceptance-in-progress.py`
and is not part of this B2 submission. Its earlier nine-file limited/dense
diagnostics remain evidence, not a completed Batch 3 acceptance.

The reviewer must independently fix the new candidate and rerun the fixed
source suite. No production push, merge, or B3 completion is claimed here.
