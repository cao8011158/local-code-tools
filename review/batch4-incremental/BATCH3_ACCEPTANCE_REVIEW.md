# B4-ACCEPTANCE — independent review round 1/3: pass

Fixed head `6a16154b7b12787696f9b334ef93342741235d73`, tree
`303b53c85330c98897d7fc46ea02731b373f81fa`; batch base
`4eb5060b724aa71ccac1dc0dd695d9abdae9fbd0`. Actual merge target remains
`feat/local-code-tools-import` at `fc857f395a381e5dfec9941d60ca685bcbe0b3fd`.
The target is the merge base; head is ahead75/behind0. Production is exactly
the accepted B2 guarded implementation; B3 adds acceptance tests/evidence.
Root did not edit production.

408 materialized files matched remote Git blobs before/after testing, zero
mismatch/local-only files. All653 unmaterialized files are historical review
evidence preserved from the full remote tree. Independently verified nine
original source files, 55,865 bytes, against fixed SM a7b0804… Git blobs and
SHA256. No replacement external modules or business execution.

Independent complete project + applicable review set: **876 passed,
32 skipped, 226.71s**. This includes the expensive nine-file test once on the
current head. The same run supplies feature acceptance evidence; it is not
counted twice. Six pre-existing diagnostic/service failures in five historical
files remain excluded exactly as the baseline records explain. Optional
service skips do not claim a live Neo4j test.

Developer pre-push full main:678/27 in178.08s, including nine files. On this
fixed remote head, developer targeted3/1deselected in13.32s and quick main
677/27/1deselected in65.56s omit only the already-run expensive nine-file
case; the independent full run includes it. Changed-test F/E9 passes.

| Acceptance | Independent result |
| --- | --- |
| Three actual files, actor literal change | Owner mode, one changed file parsed; fresh20-table equality, failure preserves old pointer, old reads, recover and next owner update, synthetic file add/delete explicit full. |
| Six actual files | Nonlimited full baseline12,807 associations. Comment-only control uses owners. Actual item_units constraint change explicitly fulls for selected opaque receiver coverage, preserving full traces/input/source records. Not claimed as a selective improvement. |
| Nine actual files | Limited at20,000 associations. 97 catalog nodes/696 edges/408 sites,517 initial Jedi queries; edit explicitly fulls and matches same-input fresh including UNKNOWN. Not a full83-file application capture or nine-file owner success. |
| Actual USearch and public queries | Frozen catalog supplies96 explicitly synthetic vector chunks/3 USearch partitions with zero provider calls. BM25/dense/exact/RRF/node/relations share the published version. No ranking-quality claim. |
| Changed callback dense lifecycle | Root-owned public test verifies first→second, interruption and old artifact hashes, both old/new graph/search views, recover then owner update, portable backup/restore and another owner update; all match fresh. |
| Pins/schema/compatibility | Existing main and related controls cover changed pins, old/missing cache/schema, source fencing and coordinated publication. No live external rules checkout or Neo4j is claimed. |

The actual six-file test discovered B4-OWN-04. Acceptance paused, B2 reopened
without resetting its first review, narrow evidence fallback and None receipt
handling were repaired, and B2 round2 passed. Its four independent controls
and the unchanged ordinary callback controls pass again on this head. The
finding is closed; no blocking prerequisite or current finding remains.

## Actual locality and total-work accounting

The public path is build → initial source capture → verified prior artifact /
AST evidence → indexed producer/container/owner inputs → selected Graph/Analyzer
→ full immutable SQLite/BM25/vector snapshot → final source fence/publication.
The source/owner reverse APIs and actual SQL plans are exercised in the full
suite, with indexed SEARCH and no unrelated table scan; reader output and
inspection byte budgets retain UNKNOWN/truncation behavior. No new MCP write
boundary was introduced.

Transparent measurement script `check_batch3_work_independent.py` ran again
from this fixed head, with an independent full oracle for each input size:

| Measured work | 0 unrelated files | 20 | 100 |
| --- | ---: | ---: | ---: |
| Changed Python parses | 1 | 1 | 1 |
| Selected owners / Jedi / associations / sites | 7 / 10 / 12 / 3 | same | same |
| Initial + publication-fence inventories | 2 | 2 | 2 |
| Decoded modules / module inventory / mounted source files | 2 each | 22 each | 102 each |
| storage.hash_artifact calls | 8 | 8 | 8 |
| Actual streamed hash bytes | 1,225,862 | 2,666,916 | 8,140,436 |
| Complete new snapshot bytes | 450,946 | 1,040,524 | 3,284,188 |
| Public single-node / relation reply bytes | 882 / 1,059 | same | same |

The constructor/mount/AST/output costs remain proportional to the capture.
Only selected solver work is local. Hash counts cover that named streaming
helper, not every source/metadata digest; capture text byte observations are
not a count of all filesystem IO. Query reply bytes do not prove internal IO
locality. Initial and repeated same-version public replies match, while the
separate source SQL tests establish actual indexed reads. No total O(K) claim,
no arbitrary wall-clock threshold, and no removal of the final source fence.
The preflight measurement's incorrect one-inventory expectation is preserved
and corrected as a test-authoring issue.

Scope limitations are explicit: existing20k budget, missing external context,
opaque receiver fallback, bounded9 input only, synthetic provider-free dense
integrity checks, optional services untested. These are not disguised as full
business/runtime precision. The approved three-batch scope is complete.

`BATCH3_EVIDENCE.json` and `batch3-review1-gate.json` bind this exact pre-merge
head and target. Prepare the evidence-only commit without advancing the tested
work ref; merge this tested head under the existing authorization, verify its
tree/parents, then persist the final merge result on the report branch.
