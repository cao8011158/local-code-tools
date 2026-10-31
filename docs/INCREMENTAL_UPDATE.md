# Incremental update planner contract (Batch 4, first layer)

## Function-value dependency design status

The [function-value dependency contract](FUNCTION_VALUE_DEPENDENCIES.md) remains a broader proposed design; the [gap audit](../review/batch4-incremental/FUNCTION_VALUE_GAP_AUDIT.md) preserves its earlier source baseline. A bounded `simple-python-v5` slice now admits captured, straight-line module dictionary literals and writes with string keys, direct same-repository `from ... import registry`, module/function aliases, and direct known-key calls. It rejects dynamic/numeric keys, conditional or loop effects, escapes, unknown helper mutation, rebindings and unsupported imports. The existing Analyzer decides targets and `UNKNOWN`; the structural proof only governs reuse.

The private `graph-sites.sqlite` sidecar has optional `value_flow_schema=1` container, entry, binding, write and read records. A missing entry has `present=false` and an exact subscription, not an asserted runtime dictionary key. `BINDS` connects source-identified aliases to one container, `ADDRESSES` the container to an entry, `WRITES`/`REACHES` supports to a read, and `USES_BINDING`/`READS`/`POSSIBLE_CALLS` link the read to its binding, entry and existing callable definition. These records are **not catalog/search/vector nodes or Neo4j projected relations**. The manifest reports compact counts, schema, coverage and `internal-sqlite-only` projection status. `FileDependencies` validates the sidecar and offers indexed exact-entry readers and bounded node/relation inspection. `python_incremental.prepare` consumes old entry subscribers, observed module readers and the one capture-wide writer-watch set alongside existing adjacency/import indexes. The broad watch can expand a real closure; it is not a key-precise performance guarantee. Old/missing/partial evidence, unsupported source shapes or incomplete analyzer witnesses fall back to full graph analysis. Identical-capture reuse copies records; local reuse replaces selected records and retains verified unrelated source records. This does not certify arbitrary dictionary or callback flow.

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
catalog and indexed graph evidence. Its `simple-python-v4` certificate accepts
only closed, explicit, absolute `from module import definition` relationships
and a narrow syntax for undecorated functions and ordinary classes. It excludes
inheritance, annotations, decorators, dynamic assignment, relative and star
imports (except the narrowly admitted `import re` below), unknown target namespaces, ambiguous modules within one repository,
and constructs whose receiver or effects cannot be certified. It is not a
general contract for real project code. The old snapshot must contain complete
per-file certificates. The new path parses changed modules and every file in
their transitive dependency component; unchanged, unselected Python ASTs remain
unparsed. Both syntax certification and component selection identify files by
`(repository, path)` and use the graph's existing local-first import resolver.

The v4 certificate admits an exact unaliased `import re` only when no captured
local `re` namespace exists. It also recognizes a bounded expression form:
exact built-in `type` checks in earlier positive `and` clauses establish dict,
string or integer operands for later comparison and subscript expressions.
It accepts `set` of an exactly guarded dict, constant set literals, integer
power/subtraction and `re.fullmatch` with guarded string arguments. Built-in
names cannot be shadowed by imports, definitions, parameters or local writes.
An expression with a newly admitted operator and an arbitrary call is rejected;
the newly admitted `re`, `re.fullmatch`, `type`, and `set` bindings cannot
escape as callable values. Plain calls allowed by the earlier certificate
remain unchanged. This certifies
the captured `item_units.py` leaf in a closed universe, but does not certify
its unsupported `availability.py` and `errors.py` siblings. Their three-file
capture still uses full analysis. A changed Python file on a v3 snapshot also
falls back because the predecessor lacks the v4 certificate.

The old file adjacency, provider import lookup, and requester import-name
indexes find callers, affected targets, and local modules that newly shadow or
stop shadowing a dependency. A selected module's new imports add their captured
targets to the component. The requester lookup uses
`import_lookup_requester(source_repository, module, source_path)`;
the same module-name index includes captured package ancestors of a selected
module, the requesting repository's import path, and an authorized target's
path. These ancestors supply Jedi's package context without parsing unrelated
modules. If a necessary namespace is ambiguous, certification fails closed.
The private `indexed-v2` sidecar also records prospective module lookup keys
without changing the original `import_requests` evidence: a named
`from pkg import foo` records both its normalized `pkg` request and possible
child module `pkg.foo`, ignoring a source alias. Repository-scoped indexes
resolve provider requests and new local shadows. This captures a formerly
missing child in a namespace package. The ancestor-layout gate checks child
requests that lack an exact base-module request from the same source: a source
requesting `pkg` is already selected by that key, while a direct request for
`pkg.child` still falls back if a new `pkg.py` can shadow it. Old `indexed-v1`
sidecars or missing v2 table, columns or indexes fall back. This repairs one
negative module lookup, not all unknown member, callback, effect or Jedi
dependencies. A pinned provider namespace absent from the captured module
catalog may leave its prospective child request scoped to the requester;
provider HEAD or cleanliness changes still cause full analysis, so this does
not certify cross-repository negative namespace lookups.
An added,
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
indexed old requests include `pkg.child` without an exact `pkg` request from
that same source; the bounded path does not infer Jedi's package-shadow
semantics from an uncovered child lookup.

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

## Local container write-scope candidate index

Within one full or selected graph analysis, `Analyzer` previously examined
every scope containing a subscript write for each literal container read. It
even included an unrelated function's fresh local dictionary write as a
`NO_EFFECT` check in another file's site evidence. The effect catalog now
classifies each such scope once: only a complete straight-line function body
whose writes reach fresh local dict/list/tuple literals through explicit local
name aliases, with constant literal contents and constant-index/value writes,
is put in buckets keyed by the existing literal allocation identity. A scope
with a parameter or imported receiver, return/escape/call, nested or dynamic
operation, rebind to an unproven value, module global or unsupported control
flow stays in the conservative fallback set. A container read inspects its
bucket, the fallback set and its own execution/owner scopes. The index does
not resolve receivers or invoke Jedi during preparation, and the historical
effect handlers still inspect all retained candidate events. Removing a
provably unrelated scope also removes its old redundant `NO_EFFECT` rows from
that site's coverage receipt; relevant and unknown origins remain.

`graph` records `slot_scope_index_build_scopes` and
`slot_scope_fallback_scopes` for one analysis preparation, separately from
`slot_scope_candidates_checked` and `slot_events_checked` for actual reads.
Identical-capture reuse performs no new preparation or checks and reports
zeros. On a selected incremental component, these counters describe that
component's new analysis, not all reused graph sites. This candidate index
does not change the separate Python source incremental certificate or make
unknown global dependencies complete.

## Partial analysis-read and writer-universe evidence

The private `indexed-v3` graph sidecar records an observed module-to-module
`container-effects` analysis read whenever `container_slots` inspects a
candidate writer scope. It also records one capture-wide
`slot-writer-universe` watch for each module whose container read may change if
a new fallback writer appears, even when no such writer exists yet. These
records are not `CALLS` or public graph edges. Nested dictionary expansion
uses the actual analysis scope at each recursive read: an outer B read of A's
copied container and A's read of C's source form B→A→C. Other association,
Jedi, callback and global analysis reads are still unrecorded; the manifest
therefore declares `analysis_dependency_coverage=partial` and these records
do not by themselves certify arbitrary Python update admission. The v5
dictionary gate uses them conservatively alongside its independent source
shape and exact entry evidence.

`graph-sites.sqlite` stores deduplicated stable module IDs, repository/path
ownership and kind in separate indexed `analysis_reads` and
`analysis_watches` tables. `FileDependencies.analysis_readers(repo,path)`
returns only observed consumers for that producer, while
`analysis_watchers(kind)` returns capture-wide consumers for a future writer
class. The latter intentionally has no repository filter. Both APIs use
indexed lookups; absent v3 schema, required columns or indexes fails closed.
Up to 20,000 combined distinct records are retained per full analysis. If the
budget is exceeded, the graph analysis still completes, but the sidecar is
marked truncated and both analysis APIs raise instead of returning an
incomplete impact set. The manifest contains only schema, partial/truncated
status and record counts, never the record lists.

Identical-capture reuse copies these relations. A certified local component
replaces selected consumers' old relations with current analysis and retains
unselected consumers only when old reads do not cross the selected boundary
and no unselected capture-wide watcher could be affected by the change;
otherwise it falls back to full analysis. It also falls back on old truncated
records, missing endpoints or a combined record budget overflow. The v5
dictionary slice admits a narrow literal-container reader and uses nonempty
read/watch evidence to select the component. The earlier v4-only certificate
exercised the empty-relation case. This partial sidecar still cannot certify
general Python dependencies. Old `indexed-v2` snapshots safely rebuild graph
analysis. A plain v4 file importing definitions from a modeled dictionary
component is outside the present mixed v5 certificate and falls back; the
slice does not claim general transitive caller support.

# Parso cache compatibility

The Python analyzer installs a process-wide compatibility wrapper for Parso
0.8.7 before constructing Jedi scripts. On insertion, including loading a
pickled tree from disk, it records the current use time. Parso still compares
the source modification time with `change_time` to invalidate changed source,
and its ordinary 600-entry cleanup still removes inactive entries. The
dependency is pinned because this wrapper uses Parso's private insertion API;
an unsupported Parso version fails explicitly. This fixes newly loaded old
source being immediately classified as inactive. It does not extend the
lifetime of a tree that really has been inactive for more than ten minutes.
