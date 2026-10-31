# B4-OWNER-UPDATE — independent review history

Current accepted code: `7f1d86e0b136a6df11cc981da053aa3c584b5f61`, round **2/3**. The initial round1 and subsequent reopening are preserved below.

Reviewed the complete `b8eb6ab5aab4554a2b5fc90204d6c12a1c2655fb` →
`4f73d150cd4831f29d042b4eb692ea845a6b64ce` batch. Candidate tree:
`0610764c87f6452714eefb4ed422433b0127d6a6`. Actual target remains
`feat/local-code-tools-import` at `fc857f395a381e5dfec9941d60ca685bcbe0b3fd`.
Root did not edit production; implementation actor was GPT-6 SOL / medium.

352 materialized files matched remote Git blobs before and after testing;
zero mismatch or local-only files. Historical unmaterialized evidence was
preserved by constructing the candidate from the complete remote base tree.
Full production diff is saved as `b2-full-production-diff.patch`.

| Requirement | Independent conclusion |
| --- | --- |
| Remove universal grammar admission | Public build uses verified source/cache/schema and actual directed inputs; `simple_python.certify()` remains descriptive metadata, not the general owner-update gate. |
| Function-level analysis | Changed files are parsed; B1 producer/site and container-origin readers plus actual owner input reads select consumers. Shared source context and module inventory are prepared once across iterations. |
| Correct replacement | Sites, edges, observations and B1 sources match fresh builds; independent sources survive deletion. Return/getter chains, callback arguments/defaults and new writes are covered. |
| Conservative uncertainty | Unknown/incomplete candidates remain; ambiguous origins, catalog changes, unsupported evidence and budgets explicitly widen or rebuild. Static output precision was not increased. |
| Cached nonempty real results | Fixed SM three-file edit reuses actual item-unit analysis without querying valid_item_unit and matches fresh private/public records. Broader complex-source acceptance is Batch 3. |
| Compatibility / failure | Corrupt/missing AST cache, old schemas, publication interruption, retry, old views and subsequent updates pass relevant controls. |

Independent full required set: **866 passed, 32 skipped, 105.34 seconds**.
The six pre-existing historical diagnostic/service failures in five files
remain excluded exactly as recorded in the baseline; 32 skips include optional
services. Developer fixed-directory checks were 673/27 and targeted 61 passed;
they overlap the independent suite and are not added to its count. Changed-code
F/E9 passes. A broader preflight lint found an unchanged unused Path import in
source_snapshot.py; this pre-existing unrelated item was not edited.

| Locality control | 0 / 20 / 100 unrelated inputs |
| --- | --- |
| Actual solver work | All three: 7 selected owners, 10 executed Jedi queries, 12 association evaluations, 3 analyzed sites; only the changed file parsed. Unrelated functions contain real calls and are not queried. |
| Module inventory | Exactly N modules once per update, including multi-pass analysis; this is necessary context preparation, not a local-work claim. |
| Source lookup, cold | 4 SQL statements, 2 supports / 1 reader / 1 subscription; VM 161 / 162 / 162. |
| Source lookup, warm | Same outputs / statements; VM 157 / 158 / 158. |
| Actual owner reverse SQL | SEARCH unit_source_supports using unit_source_producer, with DISTINCT's temporary B-tree; traced related query/row shape remains unchanged with unrelated pairs. |

The end-to-end chain is build → captured inventory and immutable integrity
checks → owner preparation → indexed source/input readers → selected-owner
Graph/Analyzer → merge → snapshot materialization/publication. File hashing,
AST decoding/validation, inventory, value metadata, cache serialization and
complete snapshot output still have full-capture costs. Related reverse
lookups can repeat across closure rounds and their work is measured. No claim
that the complete operation is O(K), and no new MCP mutation endpoint.

Three confirmed P2 problems were found and repaired before candidate publication:

- **B4-OWN-01-INPUT-SCOPE:** changing imports changed the candidate universe;
  retained owners kept stale component input events. Current policy comparison
  now selects affected owners once and reobserves their inputs, including both
  finite/capture transitions.
- **B4-OWN-02-IMPORT-ORDER:** concatenating retained and new requests changed
  ordinal order. Current merge follows full module order; unprovable mixed
  ownership rebuilds. Besides ordinal the original request content was equal.
- **B4-OWN-03-LOOKUP-SUPPORT:** boundary-sourced LOOKUP_IN bypassed owner
  deletion. It now survives only with a current unresolved IMPORTS support for
  the same lookup; two independent single/multiple-importer controls verify
  b→c→b and fresh equality.

All three are resolved on the reviewed head. Original failures, intermediate
test-authoring mistakes and fixes remain in logs. Pre-review diagnosis did not
consume or reset a formal round; this completed fixed-remote review is round 1.
There are no unresolved blocking findings. `BATCH2_EVIDENCE.json` and its gate
bind this observed code head before the evidence-only closing commit.

Proceed to approved **B4-ACCEPTANCE**. Do not merge the incomplete overall step.
No paid embedding, business code execution, external service startup or
full application graph was performed in this batch.

## Reopened during B3: B4-OWN-04-OPEN-RECEIVER-COVERAGE

The round1 verdict above remains historical. A real six-file capture, after
a comment control then item_units numeric constraint change, found a public
site explanation discrepancy: availability.query_action_availability had the
same empty targets/boundaries, UNKNOWN and completeness, but 44 association
steps/122 coverage gaps instead of fresh100/1134. Per-owner private input
events also differed. All edges and the other semantic tables matched.
The original4537843 full analyser gives the same full100/1134 result, so
this is a B2 selected-analysis integration issue, not a new upstream precision
change. The consumer was already selected; merely selecting it again is not
a fix. Actual evidence is open-receiver-input with incomplete
instance-field-coverage, an opaque input universe.

P2 confirmed/open/blocking, discovered in B3 and owned by B2. Preserve the
completed round1; pause dependent B3 acceptance and merge. The bounded repair
is a selected-consumer evidence guard with explicit full fallback where the
opaque receiver source cannot be certified. Do not reject every UNKNOWN or
complex file, remove evidence, or change full-analysis precision. Original
logs and independent positive/negative controls are retained. B2 requires a
new fixed-head round2 review before B3 resumes.

## Round 2/3: pass, B4-OWN-04 resolved

Fixed `7f1d86e0b136a6df11cc981da053aa3c584b5f61`, tree
`6cd5780e4c3269e3ab87231503c3d7dc92250842`; full B2 base remains
`b8eb6ab5aab4554a2b5fc90204d6c12a1c2655fb`. Target still fc857f3.
377 required/materialized files matched remote Git blobs before/after tests;
zero mismatch or local-only files. Unmaterialized653 are historical review.
B3 unfinished tests were held outside this fixed candidate.

Independent complete required set: **872 passed, 32 skipped, 121.05s**.
Developer same fixed directory: 675/27 in56.94s and targeted67 in38.05s;
not added to the independent count. Source/owner locality3 controls passed
in3.98s: selected7/Jedi10/associations12/sites3 remain identical with0/20/100
unrelated active functions; source cold161/162/162 and warm157/158/158,
actual indexed SEARCH plans preserved. Changed-code F/E9 passes.

The narrow selected-owner evidence guard fixes04 without changing full
analysis or dropping provenance. The actual six-file value edit now explicitly
uses full analysis and matches all semantic/input/source records. A capture
containing an opaque method still updates an unreferenced idle function by
owner. The apparent unrelated caller control had a real parameter-origin read;
that dependency remains and selects the opaque consumer. A direct self() call
has no field receipt; its None value no longer raises and its unrelated update
remains incremental. Ordinary open callbacks stay eligible.

The initial root launch used the active cwd accidentally; it was interrupted
with exit130, retained separately, and is not review evidence. The completed
round above ran from b2-review2-fixed. This execution correction did not consume
an extra formal round. Original P2 reproduction, failed test assumptions and
None-guard regression logs remain preserved.

B4-OWN-04 is resolved, no blocking findings remain. The checked gate binds
7f1d86e and the unchanged target before the closing evidence-only commit.
Resume B3 acceptance with the guarded implementation; do not treat the old
nine-file diagnostics as acceptance on this new program hash. The existing
20k full-analysis budget/limited boundary remains explicit.
