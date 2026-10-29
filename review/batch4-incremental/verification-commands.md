# Local development verification (not independent review)

Working directory: `/workspace/scratch/413372d9a5a5/lct-staged-import`.

Commands rerun after the bound-build early-rejection change:

```sh
.venv/bin/pytest -q tests/test_publication_coordination.py tests/test_lifecycle.py tests/test_attach_dense.py tests/test_official_mcp.py tests/test_official_mcp_templates.py tests/test_portable_restore.py tests/test_neo4j_staged_import.py > review/batch4-incremental/pytest-targeted.log 2>&1
.venv/bin/ruff check lct/storage.py lct/publication.py lct/cli.py lct/query.py tests/test_publication_coordination.py > review/batch4-incremental/ruff-targeted.log 2>&1
```

Exit status: both 0. Raw output is retained in the adjacent `.log` files.

Files changed by this development checkpoint:

- `lct/storage.py` — candidate callback/prepare-only, bound-version bypass guards and early rejection.
- `lct/publication.py` — terminal coordinator, binding, recovery of ambiguous acknowledgments, pinned descriptor verification.
- `lct/neo4j_graph.py` — expose projection schema in marker summary.
- `lct/query.py` — explicit version pin for search entrypoints and cursor conflict check.
- `lct/cli.py` — coordinated management and pinned official request commands.
- `tests/test_publication_coordination.py` — synthetic fault and offline integration tests.
- `review/batch4-incremental/publication-progress.md` — implementation and remaining constraints.
- `review/batch4-incremental/verification-commands.md`, `pytest-targeted.log`, `ruff-targeted.log` — test record.
