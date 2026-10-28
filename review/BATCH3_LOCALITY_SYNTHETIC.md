# Independent parser locality/behavior probe (2026-10-28)

Compared copied baseline `lct-batch3-review` (identified upstream baseline `7c50563cd695aed018bd451dec9d05a631792525`) with uncommitted `lct-batch3-parser-work`. The only production diff inspected was `lct/python_analysis.py`. No production code or candidate tests were changed. Python: `lct-round5-review/.venv/bin/python`.

Command for each case/size/version: `timeout 60s lct-round5-review/.venv/bin/python .tmp/batch3-locality-independent/probe.py lct-batch3-$version $case $n > .tmp/batch3-locality-independent/$case-$n-$version.json`. All 24 processes exited 0; no timeout. Public path `python_nodes` -> `Graph.build`; counters wrap `Analyzer.query`, `Analyzer.may_call`, and candidate iteration, including nested recursion. Each version is a separate subprocess with its own `sys.path`; source text is parsed/captured and never imported. The probes use temp dirs and no Neo4j or paid service.

All twelve case/size pairs had exact ordered site records (target sets, unknown flags and reasons, completeness basis/decision, boundaries) and exact edge multisets. One raw edge-list ordering difference in `registry-30` is resolved by multiset comparison: two `REFERENCES` edges with targets `f`/`g` swapped at positions 98/99 from unordered result iteration. IDs/versions were normalized to qualnames for cross-source comparison; structural edge fields retained. No semantic difference found.

| case | N unrelated | baseline may_call / query calls / misses | candidate candidate visits / may_call / query calls / misses | seconds baseline / candidate |
| --- | ---: | --- | --- | --- |
| base alias/callback | 0 | 27 / 32 / 9 | 16 / 16 / 21 / 9 | .198 / .231 |
| base alias/callback | 30 | 117 / 152 / 39 | 76 / 76 / 111 / 39 | .211 / .210 |
| base alias/callback | 100 | 327 / 432 / 109 | 216 / 216 / 321 / 109 | .353 / .382 |
| base alias/callback | 250 | 777 / 1032 / 259 | 516 / 516 / 771 / 259 | 1.026 / .846 |
| registry key/value | 0 | 18 / 9 / 3 | 18 / 18 / 9 / 3 | .173 / .170 |
| registry key/value | 30 | 198 / 219 / 33 | 48 / 48 / 69 / 33 | .225 / .277 |
| bound method alias | 0 | 128 / 103 / 4 | 61 / 61 / 36 / 4 | .366 / .296 |
| bound method alias | 30 | 1088 / 1093 / 34 | 121 / 121 / 126 / 34 | .341 / .377 |
| recursive association | 0 | 21 / 10 / 3 | 14 / 14 / 3 / 3 | .137 / .135 |
| recursive association | 30 | 231 / 250 / 33 | 74 / 74 / 93 / 33 | .150 / .167 |
| uncertain dynamic calls | 0 | 8 / 14 / 5 | 5 / 5 / 11 / 5 | .185 / .185 |
| uncertain dynamic calls | 100 | 208 / 314 / 105 | 105 / 105 / 211 / 105 | .426 / .386 |

The public path still has cold conservative scanning through `_site_unqueried`, explaining candidate visits increasing with unrelated sites for `base` (16 -> 516). Its benefits are strongest once a site observation is known; this probe did not separately measure a warm analyzer because `Graph.build` creates one analyzer per call. The new `_source_lines` and definition-line index are constructed once per analyzer; normal immutable capture is tested. Same-length mutation of internal `nodes`/`module_for` after initialization is not tested or claimed supported. These synthetic files do not reproduce the full business graph or cross-repository import gates; no whole graph run was performed.

## Full-scale difference triage (follow-up)

Root's independent full-scale results under `.tmp/batch3-locality-scale` have 22416 sites and 42459 edges in each run, and 28010 Jedi query misses in each. Five site records differ, all `config.get` in `packages/dnd5e-engine/src/dnd5e_engine/activities/scale.py` at lines 80, 82, 146, 152, and 155. Baseline has `jedi-no-result`, no external boundary; candidate has `builtins.dict.get` (raw manifest maps Jedi typeshed `stdlib/builtins.pyi`, line 1176), an extra boundary edge. Every differing site still has empty internal target set, `complete:false`, `unknown_origin:true`, and `association-budget`. This is a real boundary/reason difference, not merely edge ordering.

Bounded targeted diagnosis: `PYTHONHASHSEED=0 timeout 45s lct-round5-review/.venv/bin/python .tmp/batch3-locality-independent/full_capture_query.py lct-batch3-{review,parser-work} direct`, each a fresh isolated subprocess. The script extracts 4066 AST nodes and initializes one Analyzer on the same 286 captured Python modules, then queries only those five sites; it does **not** call `Graph.build`. All four processes exited 0 within ~16 s. The first baseline run returned `jedi-no-result` at 80/82 and `builtins.dict.get` at 146/152/155; the second baseline run returned `jedi-no-result` at all five. Candidate first returned the boundary at all five, then returned no-result at 80/82 and boundary at 146/152/155. The query cache was empty after initialization in the second pair, so the five were not pre-cached there. A single-module capture query on the same source returned no-result at all five in both versions. Baseline itself therefore exhibits different Jedi inference outcomes for these positions under the same source, fixed hash seed, and query order; the exact cause inside Jedi remains unverified. The candidate may still influence inference through changed call order in the full build, but these five observations do not establish a deterministic missed-candidate bug. Full-scale bitwise semantic equality is not established. No production code or database was modified.
