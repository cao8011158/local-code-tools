# Batch 3 formal review — round 1 of 3

Reviewed full remote implementation: `42b0acd95fd503551c22447613738c8d9e62bfe9`.
Merge target unchanged: `feat/local-code-tools-import` at `655b78a834c40542bf62c09bdd508c17d7f46450`.
Verdict: **prerequisite fixes supported; full Batch 3 acceptance blocked for human disposition of core inference variability and remaining feature gates. No merge.** One formal review completed; no reset of history.

## Evidence and fixes

All thirteen newly published files were fetched at the fixed SHA and verified by Git blob and byte comparison. The prior nine-file candidate was independently read and tested earlier; this review also inspected its snapshot/import contracts. Root did not implement the three production-file changes.

- B3-001 resolved for the authorized locality defect: observed-query candidate index retains unqueried/no-atom candidates, original ordering, existing may_call/resolve checks and reentrant fallback; definition-line buckets replace repeated all-node matching. No eager Jedi prepass or name-only filtering. Class-construction fallback remains unchanged.
- B3-002 resolved: explicit catalog/partition artifact membership, per-file streamed checksum/size, regular-file checks, nonempty journal/WAL rejection before SQLite open, backup membership restricted to validated artifacts and metadata. The former incidental-file failure did not recur in the corrected actual build. The failed original database was preserved.

| Independent verification | Actual result |
| --- | --- |
| Fixed remote `python -m pytest -q tests`, owned native Neo4j 5.26.0 | 441 passed, 1 skipped, 44.55 s, exit 0; one SDK deprecation warning |
| Public Graph.build synthetic differential cases | 12 baseline/candidate pairs, 24 isolated processes, equal site records and edge multisets |
| Dense missing-artifact / manifest membership / actual live WAL boundaries | 5 passed, 0.67 s; included in remote tests |
| Actual captured-source offline build | 5,957 nodes, 22,416 sites, 42,459 relations; published in 230.903 s; zero embedding requests |

The product suite is `tests/`; historical `experiments/python_graph` has its own environment and was not independently installed. The developer reported missing psutil when accidentally collecting that separate experiment. The shared Python environment is not a clean install. One opt-in test remains skipped.

Actual graph-only comparison: 245.487 -> 212.531 seconds (~13% reduction); may_call checks 1,674,750 -> 422,169 (~75% reduction); query calls 2,226,366 -> 973,785 (~56% reduction); query misses remain 28,010. Graph peak RSS 1,901,660 -> 1,951,904 KiB: **no memory improvement**. The full corrected build reached 2,374,496 KiB peak RSS, a different scope from graph-only. Cold inference and conservative unknown scanning remain; this is not an O(1) whole-graph claim.

## B3-003 — human decision, not another automatic rewrite

All 22,416 internal target sets, completeness flags and unknown-origin flags match. 22,411 full site records match; five differ at `activities/scale.py` config.get lines 80,82,146,152,155. Baseline has no external target plus jedi-no-result; candidate records builtins.dict.get. Both retain association-budget, complete=false and unknown_origin=true. 42,454 edge IDs match; five unresolved edges are replaced by five external-boundary edges. Exact semantic equality is **not** established.

Bounded diagnosis, fixed PYTHONHASHSEED=0, same captured source and five-query order: two baseline processes themselves produced different results (first boundary on last three sites, second no boundary on all five). Candidate processes also varied. Each ran about 14–16 seconds and queried only these sites after full capture initialization, not the full graph. Raw observations and reproducible scripts are saved here. This demonstrates existing inference-chain variability; precise cause in Jedi/runtime/cache order is unverified. Do not label it a proven new optimization regression or claim a proven upstream bug.

Recommended human decision: accept only this documented external-candidate variability while retaining UNKNOWN, and continue the remaining Batch 3 acceptance without claiming exhaustive calls. Alternative: authorize a separate bounded stability investigation before proceeding. This route follows batch-dev-review's core-component/out-of-current-fix boundary. No automatic dependency replacement or broader parser refactor is authorized. No confirmed P0/P1 found.

Both versions exhaust the original 20,000 association budget and report analysis_limited=true. UNKNOWN is a supported output, but this is a material coverage limitation for final user acceptance; do not silently increase limits or certify complete analysis.

## Remaining gates

Actual Voyage vectors/HNSW, real business Neo4j projection, real retrieval quality and Drive download/restore acceptance are not complete. Paid budget remains unapproved. No business repository changed and no true graph database/index/key is uploaded to GitHub. The new temporary runtime catalog is a validated lexical/graph candidate, not the final portable package. Preserve the review round and await the human disposition; do not auto-merge.
