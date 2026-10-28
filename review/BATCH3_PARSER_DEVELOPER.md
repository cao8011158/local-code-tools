# Batch 3 parser locality developer handoff

Base: isolated copy of `lct-batch3-review`, the pushed Batch 3 candidate at `7c50563cd695aed018bd451dec9d05a631792525`. Scope: `lct/python_analysis.py`, `tests/test_call_candidate_index.py`, `docs/ANALYZER_LOCALITY.md`, this report. No source capture, embedding, Neo4j, parser extraction, or business repository was edited. No push or merge.

The candidate index uses only observed `self.queries` results, keeps unqueried/no-atom sites, preserves original ordering, and retains `may_call` plus exact `resolve` checks. It does not run a Jedi prepass. Reentrant queries and dynamic site-count changes fall back to the old scan. `map_name` uses a definition-line bucket with its original matching predicates and falls back if node/module map sizes change. Source lines are cached once. Cold Jedi cost and broad unknown admission remain; neither elapsed-time nor resource savings at business scale has been established.

Targeted local test command:

```sh
/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python -m pytest -q tests/test_call_candidate_index.py tests/test_python_pipeline.py tests/test_python_review_round3.py tests/test_python_review_round4.py tests/test_core.py --basetemp=.tmp/parser-targeted --junitxml=/workspace/scratch/413372d9a5a5/.tmp/batch3-parser/targeted.xml
```

Exit 0: 148 passed, 1 opt-in test skipped in 3.35 seconds. Raw stdout/stderr `/workspace/scratch/413372d9a5a5/.tmp/batch3-parser/targeted.log`, JUnit `targeted.xml`. An initial infrastructure run had 146 setup errors because `.tmp` did not exist; after creating it, one targeted regression exposed dynamic node-map mutation, and the production index gained its original-scan fallback. The passing command above is after both corrections. Shared `.venv` is linked; no clean-install claim. Full nonservice command (exit 0):

```sh
/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python -m pytest -q tests -k 'not neo4j' --basetemp=.tmp/parser-full --junitxml=/workspace/scratch/413372d9a5a5/.tmp/batch3-parser/full.xml
```

Result: 417 passed, 1 skipped, 12 deselected in 11.16 seconds. Raw stdout/stderr `/workspace/scratch/413372d9a5a5/.tmp/batch3-parser/full.log`; JUnit `full.xml`. No shared Neo4j service or business build was started.
