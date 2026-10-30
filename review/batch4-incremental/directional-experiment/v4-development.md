# V4 developer report: constructor change seed

This is the user-authorized fourth bounded experimental repair after the third independent review. It does not reset that review count or establish production readiness. V1–v3, production `lct/*`, tests, and the cumulative stage report remain unchanged. Run from the project root:

```sh
PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/directional-experiment/v4.py
```

`v4-run.log` records the run; `v4-results.json` holds all candidate/full normalized differences and costs. The command exits 0 when collection finishes; **26/27 strict comparisons match**, with the one failure retained below. The suite is the v3 development 20, all three independent-v3 probes, and four new constructor cases. No real graph store, API, or Neo4j was used.

## Selection change

V4 indexes captured definitions using `(path, complete qualname, kind)`, rather than a method's final name segment. For a changed, removed, or added `Class.__init__`, it identifies the old containing class through `CONTAINS` (or exact class identity for an added initializer on an existing class), enqueues that class, and follows old reverse CALLS to constructor consumers. It then applies v3's conservative return-state propagation: the unchanged factory returning a `Box` instance forwards impact to its callers despite the equal class atom. An initializer's implicit `None` return does not stop constructor-state propagation. The changed top-level function path and call-shape logic remain bounded as before; caller summaries now use complete qualnames.

| Targeted case | Strict match | Selection | Outer sites selected/full | Graph Jedi selected/full |
|---|---:|---|---:|---:|
| Root `Box.__init__` field change, unchanged factory | yes | a,b | 3/3 | 4/4 |
| Two `__init__` names in separate source files | yes | a,b; excludes unrelated c,d | 3/6 | see JSON |
| Added initializer on existing class | yes | a,b | 3/3 | see JSON |
| Changed initializer consumed by constant-return factory | yes | a; excludes b | 1/2 | 3/3 |
| Two `__init__` names in the same source file | **no** | a,b; excludes c | 4/6 | 8/8 |

The original 20 v3 fixtures and all three prior independent-v3 probes match; the latter includes object-field extraction through another function and the constant-discard stopping control. The 21-file shared-helper case remains 0/20 selective outer sites and 20/40 selective/full graph Jedi queries. Its summary preparation still captures **21 old + 21 new AST contexts**, evaluates two summaries with one association on each side, and then builds a complete 21-file candidate context and global non-CALLS relations. These costs are separate from old/full comparison builds and do not establish end-to-end incremental savings.

## Preserved failure: same-file proof versions

In `same_named_initializers_isolated`, Alpha and Beta live in `a.py`, and only Alpha's `__init__` changes. The selector appropriately follows Alpha to `make_alpha` and `b.py`, leaving Beta's caller `c.py` out. The reused `c.py` call site has the same selected callback target (`first`), completeness, UNKNOWN state, and every non-version field as the full result. The strict site comparison nevertheless has one missing and one extra site record. A recursive comparison of those records found exactly **12 differing leaf paths**, all ending in `version_id`, under `resolution_decision.write_source_coverage` in nested `call_access.definitions` and `unused_inputs.dependencies[].evidence` (including repeated `checks` and `events` trees). The old proof references versions of definitions in `a.py`; a fresh capture gives those definitions new version IDs after the file edit. The raw mismatch remains `equal=false` in `v4-results.json`; no normalizer change or forced reanalysis of the unrelated caller masks it.

This is a concrete provenance-reuse limit even when target semantics are unchanged. V4 does not rebind old proof metadata to fresh definition versions. An implementation must either refresh such site evidence or conservatively invalidate its consumers; equal CALLS targets alone do not certify the entire stored record.

Other boundaries remain: only direct top-level function changes and `__init__` changes seed this experiment. Arbitrary method edits, mutation after construction, dynamic dispatch, reexports, missing old CALLS, changed identities, and general added/deleted class/module effects lack a completeness certificate or full fallback. The matched fixtures support this narrow mechanism, not a general incremental scheduler or a production integration.
