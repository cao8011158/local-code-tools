# Incremental update planner contract (Batch 4, first layer)

`lct.incremental.plan_update(previous, current)` compares two **already captured**
inventories. It does not read source files, consult Git, run Jedi, analyze a graph,
request embeddings, or publish a snapshot. The caller supplies `files` with
`repository`, `path`, and `sha256`; `repositories` with `name`, `head`, `branch`,
and other captured provenance; `config_hash`, `program_hash`, and an explicit
`dependency_pins` mapping. The empty mapping means pins were checked and none
apply. Missing pin attestation is an error, not evidence that pins did not change.
Missing or empty revision/build identifiers also fail closed. A change to the
captured `is_test` flag changes candidate partitions even if file bytes match.

The JSON-compatible result lists `changed` (added or modified paths) and
`removed` separately. Rename is an addition and a removal even when bytes match.
`change_kind` distinguishes `no-op`, `docs-only`, `python-change`,
`metadata-only`, and `other-change`. `affected_embedding_partitions` is a
candidate set by repository, kind and test status, not a claim that vectors
must be recomputed; configuration/program changes use `*` as an all-partitions
marker. A pin or commit-only change has no source-driven embedding candidates.

Any observed change currently returns `analysis_scope=full-capture` and
`full_analysis_required=true`. `extract.extract` hashes every included file in
a repository into its `snapshot_id`; `python_nodes.identity` includes it in
every Python `version_id`, and `Analyzer.site` includes it in every `site_id`.
Thus even a documentation edit changes the version identity of Python evidence
in the same repository. `Analyzer.parameter` and `registry_arguments` also
inspect project-wide candidate call sites; its in-memory dependencies do not
capture all negative name lookups, alias/callback candidates, Jedi project
dependencies or transitive effects across snapshots. Reusing site proofs or
recomputing only edited files would lose candidates and UNKNOWN origins.

The planner does not implement true incremental analysis and is deliberately
not wired into `storage.build`. The existing `storage.build` still analyzes the
whole captured graph and uses content differences for SQLite writes and cached
embeddings. A later dependency-aware implementation must maintain complete
positive, negative and unknown reverse dependencies, validate identity and
coverage, and fall back to full analysis whenever its closure cannot be proved.

## Captured unresolved named-import lookup (foundational dependency slice)

When `from A import name` has no resolved binding and `A` is one unique captured module allowed by the repository dependency pin, the graph retains an unresolved `IMPORTS` edge from its lexical importer to a named boundary endpoint. Its stable logical endpoint derives from the captured module's repository, module name, and requested name (not the alias or call spelling). A `LOOKUP_IN` edge joins that boundary to module `A`. The `IMPORTS` raw edge retains the original Jedi/LCT unresolved reasons, `unknown_origin`, and `complete=False`; the `LOOKUP_IN` edge says only that the lookup namespace was captured. It is not a call or proof that the name is absent. Multiple importers of the same missing name may share the boundary; different repositories or names cannot collide. A successful import retains its existing direct resolved `IMPORTS` target.

SQLite persists both relations in the snapshot's edges table, with existing `(source,kind)` and `(target,kind)` indexes. The public relation traversal can follow this one boundary class in either direction, including the reverse `A <- LOOKUP_IN <- boundary <- IMPORTS <- B` path. Neo4j projects the logical endpoint into a scoped `LCTBoundary` with category `unresolved`, lookup repository/module/name/status and a generic `named-import-unresolved` reason; the precise per-site reasons remain on raw `LCTEdge`. Its physical boundary ID retains the v2 `external:<logical-endpoint>` convention. `Neo4jGraph.get_relations` accepts the logical endpoint; official `node_read_cypher_requests(..., boundary=True)` accepts the physical boundary ID returned with a relation row. Native `IMPORTS` and `LOOKUP_IN` relationships are both indexed by scoped endpoint identities. Existing null-target unknown imports, external boundaries, ambiguous module names and pin mismatches retain their previous behavior.

This captures one negative lookup dependency. It does not establish complete invalidation for successful imports, reexports, conditional imports, Jedi internals, aliases and callbacks, or cross-snapshot reuse. The planner still requests full-capture analysis for source changes. Old snapshots remain immutable and readable; the new edge appears only in a newly built snapshot. No public schema or parser replacement is introduced.
