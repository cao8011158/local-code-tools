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

The planner remains separate from `storage.build`. The build path now has
additional private, certified reuse and bounded graph preparation described
below; the planner's `full-capture` flag does not describe those later gates.

## Narrow private Jedi observation reuse and import dependency inventory

The public build now stores certified direct lexical definition observations in
an indexed private table inside `graph-sites.sqlite`. A one-time AST pass per
module checks for a unique undecorated definition without another name binder.
On a later build it verifies
the old source inventory and graph evidence artifact once, checks program/config,
Python/Jedi runtime, relevant captured Python path/bytes/test membership and repository
semantic metadata, and compares freshly computed dependency-pin bindings. A
documentation-only commit can change HEAD and repository snapshot IDs without
changing those Python semantic inputs. If another Python module changes, only
an unchanged module's direct **function-local nested definition** is eligible;
module globals remain fresh. `Analyzer.query` retrieves the requested observation
by indexed position, verifies its row and current lexical certificate, and rebinds
the exact target's current version ID. Assignment mappings,
external/failed observations and incomplete input checks still invoke Jedi. AST
inventory, LCT association, adjudication, all site evidence, nodes and edges are
rebuilt under the current public repository-wide snapshot identity. The graph
records `jedi_queries_reused` and `query_reuse_reason`; this is a narrow inference
reuse path, **not** partial graph analysis for Python changes. Tests instrument
`jedi.Script.infer` to confirm that the changed module still invokes Jedi while
an unchanged nested local lookup does not. A changed external package that alters
an assigned target also invokes Jedi anew.

The same private graph evidence artifact stores each uniquely captured named
import's source module, requested namespace/name, resolved target IDs and target
modules (or unresolved status). Indexed namespace and target-module reverse
lookups can trace successful imports through reexports as well as unresolved
lookups. `module_import_dependents` exposes only that import reachability; it
cannot certify all caller, callback, receiver/effect, Jedi or negative member
dependencies. Python changes outside the certified subset still run full graph
analysis. Missing import dependencies outside uniquely captured
namespaces remain unknown and require the full fallback. Dense partitions are
reused only when their source vectors/order and configured representation match;
the public build reports reused and rebuilt partition counts separately.

## Captured unresolved named-import lookup (foundational dependency slice)

When `from A import name` has no resolved binding and `A` is one unique captured module allowed by the repository dependency pin, the graph retains an unresolved `IMPORTS` edge from its lexical importer to a named boundary endpoint. Its stable logical endpoint derives from the captured module's repository, module name, and requested name (not the alias or call spelling). A `LOOKUP_IN` edge joins that boundary to module `A`. The `IMPORTS` raw edge retains the original Jedi/LCT unresolved reasons, `unknown_origin`, and `complete=False`; the `LOOKUP_IN` edge says only that the lookup namespace was captured. It is not a call or proof that the name is absent. Multiple importers of the same missing name may share the boundary; different repositories or names cannot collide. A successful import retains its existing direct resolved `IMPORTS` target.

SQLite persists both relations in the snapshot's edges table, with existing `(source,kind)` and `(target,kind)` indexes. The public relation traversal can follow this one boundary class in either direction, including the reverse `A <- LOOKUP_IN <- boundary <- IMPORTS <- B` path. Neo4j projects the logical endpoint into a scoped `LCTBoundary` with category `unresolved`, lookup repository/module/name/status and a generic `named-import-unresolved` reason; the precise per-site reasons remain on raw `LCTEdge`. Its physical boundary ID retains the v2 `external:<logical-endpoint>` convention. `Neo4jGraph.get_relations` accepts the logical endpoint; official `node_read_cypher_requests(..., boundary=True)` accepts the physical boundary ID returned with a relation row. Native `IMPORTS` and `LOOKUP_IN` relationships are both indexed by scoped endpoint identities. Existing null-target unknown imports, external boundaries, ambiguous module names and pin mismatches retain their previous behavior.

This captures one negative lookup dependency. By itself it does not establish
complete invalidation for successful imports, reexports, conditional imports,
Jedi internals, aliases and callbacks, or cross-snapshot reuse. The separate
bounded gate below certifies a strict subset. The planner still requests
full-capture analysis for source changes. Old snapshots remain immutable and
readable; the new edge appears only in a newly built snapshot. No public schema
or parser replacement is introduced.

## Certified bounded Python components across repositories

`storage.build` can prepare a changed Python component from an old immutable
catalog and indexed graph evidence. Its `simple-python-v3` certificate accepts
only closed, explicit, absolute `from module import definition` relationships
and a narrow syntax for undecorated functions and ordinary classes. It excludes
inheritance, annotations, decorators, dynamic assignment, relative and star
imports, unknown target namespaces, ambiguous modules within one repository,
and constructs whose receiver or effects cannot be certified. It is not a
general contract for real project code. The old snapshot must contain complete
per-file certificates. The new path parses changed modules and every file in
their transitive dependency component; unchanged, unselected Python ASTs remain
unparsed. Both syntax certification and component selection identify files by
`(repository, path)` and use the graph's existing local-first import resolver.

The old file adjacency, provider import lookup, and requester import-name
indexes find callers, affected targets, and local modules that newly shadow or
stop shadowing a dependency. A selected module's new imports add their captured
targets to the component. The requester lookup uses
`import_request_requester(source_repository, requested_module, source_path)`;
old sidecars without that index fall back to full graph analysis. An added,
removed or modified package `__init__.py` also falls
back: an initializer can shadow dotted child requests beyond an exact-name
reverse index. For a matched
dependency, `Graph.imported` requires the exact configured revision, target
HEAD, and a clean target Python worktree. A pin, HEAD, or cleanliness binding
change also falls back to the full graph. A verified source snapshot does not
substitute for the Git cleanliness proof in that policy. Changes to documents,
`pyproject.toml`, other non-Python input, configuration or incompatible old
evidence retain their existing conservative fallback.
Adding or deleting an ancestor module such as `pkg.py` also falls back when
indexed old requests include `pkg.child`; the bounded path does not infer
Jedi's package-shadow semantics from an exact child module lookup.

Jedi analyzes a requesting repository in its own captured project, with its
source roots ahead of only graph-authorized, exact-pin dependency roots and
the controlled library paths. The graph still checks each returned definition
against the import policy. This avoids another repository with the same full
module name winning a query through a shared project. Captured-source hashes,
definition identities, versioned site evidence and the association budget
are checked before unchanged evidence is rebound; unsupported ownership or
versioned evidence returns to full analysis. Public graph records are exact
under this gate; `analysis_scope.mode=certified-simple-python-component`
reports the bounded path and its parsed/reused file counts.
