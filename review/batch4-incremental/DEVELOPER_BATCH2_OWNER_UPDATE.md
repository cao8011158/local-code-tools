# Batch 2 owner update: developer freeze

Production code is frozen at the SHA-256 entries in
`DEVELOPER_BATCH2_SHA256.txt`. This is a development handoff for independent
review, not an acceptance claim or a remote commit. Batch 1 source origin
records remain the dependency substrate.

## Scope and implementation

The public `storage.build` first verifies the capture, source hashes, old
artifact manifest, owner input schema, B1 source schema and AST cache. Missing
or incompatible owner evidence performs a cold full build. Changes seed all
owners of each changed Python file. Changed files are parsed in full;
unchanged ASTs load through a capture-bound JSON codec that preserves
module/definition object identity and validates source hashes. One Analyzer
carries the complete captured context across selected-owner closure passes;
only selected execution owners query Jedi, resolve and adjudicate. Old
unknown/incomplete candidates are retained. Closure uses B1 source reverse
reads, subscriptions by container origin, recorded owner analysis reads and
import/parameter/return input relationships. New writer receiver proof
accepts only unique, unconditional direct binders; ambiguous or opaque
effects fall back to full. Receiver proof does not imply an exact call target.

The selected owner merge replaces that owner's sites, edges, observations,
imports, source supports, subscriptions and writes; unselected evidence is
rebound to the current capture. Value evidence is regenerated as necessary
with retained read witnesses. Certificate and coverage fields describe the
fresh capture and never act as a grammar admission gate. On failure the old
published snapshot remains. Metrics separate preflight fallback work from
successful owner work and accumulate all closure rounds.

## Static verification

All commands ran after the final production edit, from the repository root:

- `.venv/bin/pytest -q tests/test_owner_incremental.py tests/test_dependency_origins.py review/batch4-incremental/test_owner_update_independent.py review/batch4-incremental/test_owner_effect_origins_independent.py review/batch4-incremental/test_dependency_origins_independent.py review/batch4-incremental/test_source_origin_unknown_inputs_independent.py > review/batch4-incremental/developer-batch2-freeze-targeted.log 2>&1`: 54 passed.
- `.venv/bin/pytest -q tests > review/batch4-incremental/developer-batch2-freeze-main.log 2>&1`: 670 passed, 27 skipped.
- `.venv/bin/ruff check lct/graph.py lct/python_analysis.py lct/storage.py lct/unit_evidence.py lct/unit_incremental.py tests/test_owner_incremental.py --select F,E9`: all checks passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed.

The closed-world consecutive first→second→first test checks both owner
updates against fresh sites and B1 source tables. Its fixture takes one
closure pass; the independent open/closed two-pass test is owned by the
reviewer. The interrupted `developer-batch2-final-review.log` is **not**
verification. Historical review tests still require owner-side expectation
synchronization and fixed-source independent rerun.

## B1 close to B2 production whitelist

- `lct/graph.py`: selected owner traversal and retained Analyzer lifecycle.
- `lct/python_analysis.py`: selected candidate and exact execution-owner
  input observations; B1 source recording remains.
- `lct/storage.py`: verified owner admission, merge/persistence, metrics.
- `lct/unit_evidence.py`: new private AST codec and owner input records.
- `lct/unit_incremental.py`: new directed owner scheduler, writer proof,
  closure and merge.
- `docs/INCREMENTAL_UPDATE.md`: public behavior and fallback documentation.

`lct/dependency_origins.py` is the already accepted B1 source module;
its digest is included for unambiguous combined source identity. The old
checkpoint's coarse unit dependencies/name watches are not restored.

## Project test expectation changes

All changed project tests still execute their existing full-build semantic
oracle where present. The main suite and the owner/B1 controls compare sites,
edges and B1 records for actual owner updates. The changed expectation
categories are:

- `test_actual_item_unit_incremental.py`,
  `test_dictionary_value_flow.py`,
  `test_mixed_dictionary_components.py`: valid owner evidence now selects
  `incremental-owners`, parses the changed file once, and retains unaffected
  files; fresh semantic comparison remains in these tests.
- `test_general_passive_incremental.py`: valid existing owner evidence
  selects changed owners (including the actual three-file item-unit bytes);
  newly added/deleted Python membership or unresolved origins fall back to
  full. Parsed-file counters include the actual failed preflight if any.
  Existing semantic comparisons and failure-publication check remain.
- `test_analysis_dependency_sidecar.py`, `test_analysis_inputs.py`,
  `test_changed_python_gate.py`, `test_common_python_certificate.py`:
  missing owner schema or ambiguous effects use full, while a second
  generation with valid schema selects owners. Existing semantic or
  association bounds remain; the fallback reason is asserted when specific.
- `test_cross_repository_python_incremental.py`,
  `test_relative_python_incremental.py`, `test_source_prepare.py`:
  added/deleted Python membership, changed owner catalog, relative import
  uncertainty, or legacy sidecar use full; an unchanged captured catalog with
  valid evidence can use owners. Existing fresh full comparisons remain on
  their respective tests.
- `test_analysis_inputs.py` and the B1
  `test_dependency_origins.py` old local-mode expectations now reflect
  full or owner evidence, respectively.

No root-owned `review/test_*.py` assertion was edited by the developer.
The prior historical log recorded 69 failed/120 passed/5 skipped while
source edits were still ongoing, predominantly old mode/parse assertions;
it is not a frozen semantic result. Review-owned updates and fresh-oracle
verification belong to the independent fixed-source round.

## Conservative boundaries

Membership/pin/context changes, ambiguous receiver aliases, unknown
container effects, unsupported cache/schema, and partial old value evidence
with nonempty records can force a full build. The implementation does not
increase Jedi or value-flow inference precision; candidate UNKNOWN and
incomplete provenance must match a fresh full build. Neither an unchanged
source hash alone nor an old complete site alone is a reuse certificate.

## B2 preflight repair and final freeze (supersedes earlier counts)

Independent preflight identified two metadata and one auxiliary relation
mismatch after historical route expectations were synchronized:

1. A new caller import can change the complete-capture candidate component.
   Old unselected owners carried an obsolete component scope. In the first
   graph pass, the scheduler now compares each old owner input event with the
   new Analyzer candidate component once, expands only mismatched actual
   owners, and reruns those owners. It handles finite→capture and
   capture→finite. The test compares both consecutive updates with fresh
   sites, scopes, members, consumers and import requests.
2. Import request rows were complete but retained rows had been prepended to
   fresh rows, changing persisted ordinal. Requests are now ordered by the
   complete module node order; a module mixing retained and fresh import
   owners without recorded site ordinals falls back to full.
3. A LOOKUP_IN relation can have a boundary source shared by two importers.
   A removed IMPORTS from a selected owner had left its old auxiliary edge.
   Current unresolved IMPORTS records now supply the exact boundary/lookup
   support set; LOOKUP_IN remains iff at least one current importer supports
   that relation. Both one- and two-importer b→c→b chains compare all raw
   edges to fresh full.

The repaired code was static during the following verification:

- `.venv/bin/pytest -q tests/test_owner_incremental.py tests/test_dependency_origins.py review/batch4-incremental/test_owner_update_independent.py review/batch4-incremental/test_owner_effect_origins_independent.py review/batch4-incremental/test_dependency_origins_independent.py review/batch4-incremental/test_source_origin_unknown_inputs_independent.py > review/batch4-incremental/developer-batch2-repair2-targeted.log 2>&1`: **57 passed**.
- `.venv/bin/pytest -q tests > review/batch4-incremental/developer-batch2-repair2-main.log 2>&1`: **673 passed, 27 skipped**.
- Ruff F/E9 and `git diff --check`: passed.

The independent reviewer owns its synchronized historical suite and new
candidate/auxiliary relation controls. These are not reported as passed here
until the fixed-source independent run completes. The SHA-256 manifest below
is regenerated after these repairs; older freeze logs remain as development
history only.
