# Changed-Python local graph slice — development result

The public `storage.build` path now attempts a bounded local graph update before
full Python extraction when an old complete capture carries `simple-python-v1`.
The certificate accepts a single Python repository with only plain functions,
direct imports of uniquely captured functions, and simple function body calls,
assignments, returns and constants. Other syntax and uncertain evidence use the
existing complete build. The old certificate is recorded in the manifest and
per-file source hashes in the checksummed graph sidecar. Old catalog and sidecar
are checked before reuse.

Changed files seed an indexed old adjacency/import-request closure. New direct
imports add their captured target to that closure. Each selected file is parsed
once; unchanged files outside it use the old catalog after independent captured
source checks and repository snapshot/version identity recomputation through the
extractor's shared version helper. Reused typed evidence rejects unknown proof
shapes or stamps. Existing atomic candidate publication and complete catalog
output remain in use. Public metrics separate preflight/full fallback parse count,
selected AST context, reused nodes/sites/edges and complete output rows.

The independent synthetic callback fixture (0 and 20 disconnected files) parses
only a.py and b.py, and the added direct import fixture parses a.py, b.py and u.py.
In each, complete node/edge/site/private records match a forced full build;
failure before publication leaves the old version readable and retry matches.
Class/constructor changes, unresolved/external import, more than one Python
repository, simultaneous document change, old sidecar/catalog failure, unknown
proof shape, or combined association budget over 20,000 fall back. This is a
bounded certificate, not a general Python dependency scheduler. Neo4j, actual
repository data and paid embedding calls were not exercised.

Final development commands (no fixed remote commit yet):

* `PYTHONPATH=. <existing-venv>/bin/python -m pytest -q tests review/batch4-incremental/test_changed_python_independent.py`: 517 passed, 25 skipped, exit 0; `changed-python-fast-final.log`.
* `ruff check` on seven changed production/test files plus the new gate test: all checks passed, exit 0; `changed-python-ruff-final.log`.

The previous Ruff import/unused-variable findings were fixed, and its earlier
log remains `changed-python-ruff.log`. One old source-prepare test expectation
changed because adding a plain standalone module is now legitimately eligible
for local analysis; unsupported class and simultaneous document changes have
explicit full fallback tests. No production code was pushed by the developer.
