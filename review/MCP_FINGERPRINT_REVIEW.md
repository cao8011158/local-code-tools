# B3-004 — user-authorized Batch 2 narrow reopening review

Base: `c6fd24335f3f96387c09ba4897fbce14713db970`. Reviewed implementation: `caa9d1ee6c54187580061eb90932e72d578e83e4`. Working branch: `feat/full-business-graph-indexes`. Target remains `feat/local-code-tools-import` at `655b78a834c40542bf62c09bdd508c17d7f46450`.

## Authorization and outcome

After the remaining startup defect and prior three-round limit were explained, the user said “好 那么请继续”; after the scope discussion they confirmed “那就不换了 继续工作把 再有需求我们再来 refactor 这个库”. This is one explicitly reopened narrow review after Batch 2's prior 3/3, not a reset. B3-004 is **addressed**. No new confirmed blocking defect was found. Batch 3 remains at 2/3, with real-data acceptance outstanding. No merge.

## Root cause and repair

`create_app()` lifespan previously called `snapshot_info()` but only used its fingerprint. Full graph/source metadata therefore loaded unnecessarily during startup. `Neo4jGraph.snapshot_fingerprint()` now validates scope and reads exactly one scalar from the complete marker in a READ session. There is no `_read()` wrapper or metadata/chunk traversal. The unique namespace/version constraint remains unchanged. Startup preserves failure redaction and driver closure. `graph_status` still requests full metadata explicitly; it is not silently reduced to a summary.

The root reviewed the full narrow delta and relevant caller/query/cleanup contracts, independently of the developer's result. The remote head was checked; 117 available tracked files in a separate review source snapshot matched remote Git blob hashes. Installed dependencies were reused, so this is not a clean-machine installation claim.

## Independent verification

Owned native Neo4j 5.26.0 with 384 MiB heap; Python 3.12 existing environment:

`python -m pytest -q tests --junitxml=review/fingerprint-fix/independent-tests.xml`

**462 passed, 1 skipped, 1 warning in 72.47 seconds.** Exit code 0. The skip is the explicitly optional real-cache test. The warning is the existing HTTP MCP client deprecation. The owned database service was stopped by its launcher.

- Root-authored native check: a complete marker with no graph/source metadata supports fingerprint access and real ASGI startup, with `snapshot_info()` deliberately forbidden.
- Root-authored native check: incomplete marker, missing version, and different namespace are rejected.
- Reviewed and rerun focused tests: exactly one scoped marker query, no metadata or redundant wrapper, no query for invalid scope, missing/null identity rejection.
- Reviewed and rerun HTTP lifecycle tests: startup calls fingerprint once and status zero times; explicit authenticated graph_status returns full source metadata; failure redaction, closure, expired token and audience/scope protections remain.
- Existing actual HTTP MCP/native graph suite and staged-import fault tests also passed in this same run. No new business-scale test was needed for a marker-only access change.

The developer's earlier unfiltered no-service run had three fixture setup errors; these remain recorded rather than relabeled as passing. The above independent service-enabled run closes that validation gap.

## Identity boundaries and deferred work

Existing `manifest.repositories` stores each repository's commit HEAD; `source_fingerprint` hashes the selected file identities/content. `program_hash`, `config_hash`, model/dimension/dtype and index version are separate existing manifest fields. Neo4j graph fingerprint hashes its normalized graph/source payload, not the vector files. Startup reads that graph identity; it does not compare all external vector/BM25 artifacts or check current remote main branches.

The discussed source-commit combination and build identity distinction is sound; this repair does not rename existing fields or migrate the schema. The proposed current-plus-previous retention policy is not newly automated. Voyage remains fixed as requested.

No parser refactor, index rebuild, paid API call, real database upload, or merge occurred. Next Batch 3 gate is regeneration/persistence and real graph import verification; vector/Drive restore acceptance remains outstanding. Do not treat this narrow pass as full Batch 3 acceptance.
