# Batch 3 bounded Neo4j graph developer handoff

Source snapshot: verified Batch 2 restore copy at `655b78a834c40542bf62c09bdd508c17d7f46450`, default branch `feat/local-code-tools-import`. This is an isolated file copy, not a Git checkout. Scope is `lct/neo4j_graph.py`, `tests/test_neo4j_bulk_import.py`, this handoff and `docs/NEO4J_FULL_GRAPH.md`. Root owns independent pushed review and gate decision.

The import now accepts at most 50,000 nodes, 500,000 edges, 128 MiB canonical snapshot, and 1 MiB per record. Fixed-whitelist `UNWIND` chunks cap 500 records / 1 MiB parameters; one 300-second transaction atomically commits all node, edge, native relation and complete-marker writes. Query IDs remain capped at 500 and result limits at 5,000. Existing raw graph/UNKNOWN/external endpoints/source identities and fingerprint conflict semantics are retained. This is bounded full-size capacity, not measured production throughput or an incremental index.

Focused owned Neo4j 5.26 test run: 8 passed in 22.49 seconds, exit 0, at `/workspace/scratch/413372d9a5a5/.tmp/batch3-graph/focused.log` and `focused.xml`. It covered new 1,200-node/6,000-edge real service fixture plus prior small graph and independent Neo4j tests. The first run identified a Cypher brace typo; it was fixed before this passing rerun. Full owned-service suite command (exit 0):

```sh
/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python /workspace/scratch/413372d9a5a5/.runtime/neo4j-batch1/run_with_neo4j.py /workspace/scratch/413372d9a5a5/lct-batch3-graph-work /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python -m pytest -q tests --basetemp=.tmp/bulk-full --junitxml=/workspace/scratch/413372d9a5a5/.tmp/batch3-graph/full.xml
```

Result: **418 passed, 1 opt-in test skipped, 1 SDK deprecation warning** in 34.74 seconds. Captured stdout and stderr: `/workspace/scratch/413372d9a5a5/.tmp/batch3-graph/full.log`; JUnit: `/workspace/scratch/413372d9a5a5/.tmp/batch3-graph/full.xml`. The helper starts/stops an owned Neo4j Community 5.26.0 service with 384 MiB heap and 128 MiB page cache. Shared `.venv` is linked from `lct-round5-review`; this is not a clean dependency install. The first full run had 417 passed and one failure from reusing a persistent test namespace on rerun; the test now uses a unique namespace, and the complete rerun passed. No source business build or paid API was used. Synthetic 1,200/6,000 success is not a performance benchmark or proof at the 50,000/500,000 ceiling.
