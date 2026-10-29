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
