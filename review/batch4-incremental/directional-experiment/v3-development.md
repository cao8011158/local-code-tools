# V3 developer report: conservative return-state propagation

This research-only `v3.py` builds on v2 without modifying v1/v2, production `lct/*`, or tests. Run from the project root:

```sh
PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/directional-experiment/v3.py
```

The captured run is `v3-run.log`, and `v3-results.json` contains the normalized candidate-versus-independent-fresh-full differences, selection, and costs for every case. Exit code 0 means the experiment completed; inspect each `equal` field for correctness. This run has **20/20 matching cases**: the original v2's 15 cases, both root-authored independent v2 cases, and three v3 fixtures. The v2 historical results were not overwritten.

## Change and result

The old same-class counterexample changes `Box(first)` to `Box(second)` inside `factory`, while `factory().cb()` lives in another file. V2 resolves both factory returns to the same `instance` atom (the `Box` class) and stops, leaving the downstream CALLS edge/site stale. V3 treats equality of those atoms as insufficient evidence about the instance's fields. When a changed top-level function body returns a non-literal, unknown, empty, or incomplete resolution, it seeds the old CALLS return-consumer worklist even if the atom summary is unchanged. At each reached caller, the worklist continues if the caller's return summary changed **or** its return may carry unmodeled state. A complete bare or literal return can stop this additional state propagation. Visited IDs still terminate cycles.

| Case | Match | Selected files | Outer sites selective/full | Jedi selective/full | Summary preparation Jedi old+new |
|---|---:|---:|---:|---:|---:|
| Root same-class field counterexample | yes | 2/2 | 3/3 | 4/4 | 0+0 |
| Direct `return Box(first)` changed to `Box(second)` | yes | 2/2 | 3/3 | 4/4 | 0+0 |
| Same-class return forwarded via local in another function | yes | 3/3 | 4/4 | 6/6 | 1+1 |
| Unrelated local scalar edit; `return 7` | yes | 1/2 | 0/1 | 1/2 | 0+0 |
| Shared-helper unused local, 20 importers | yes | 1/21 | 0/20 | 20/40 | 0+0 |

The preceding 15 v2 cases also match, including keyword callback, module-level callback, cycle, direct return, local-binding return, and literal selector variants. The independent v2 forwarding case matches. V3 preparation captures and indexes **all old and new AST catalogs**: for the 21-file helper fixture, 21 old plus 21 new context files and two return-summary evaluations (two associations), followed by a 21-file candidate graph pass. Its non-CALLS passes still run globally. The 20/40 Jedi ratio is for the selective/full graph passes only; the summary's old/new Jedi counts are separate. The harness also performs old and fresh-full builds for comparison, which are not candidate savings. No end-to-end incremental speedup, proportional parsing, or global relation locality is established.

## Boundaries

This is a bounded correctness probe, not a sound general scheduler. The propagation starts from changed **direct top-level functions** and follows known old CALLS edges. It does not certify changes confined to class constructors or methods, mutation after return, closures, dynamic dispatch, reexports, aliases, calls missing from the old graph, or changed node identities. Its narrow literal stopping rule is a heuristic over the current Analyzer summaries, not a proof for arbitrary Python context or side effects. A production integration would need a complete dependency certificate or a conservative full fallback outside the proven subset. Graph IDs/provenance reuse is not validated. No graph store, API, or Neo4j was used.
