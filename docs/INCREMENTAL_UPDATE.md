# Incremental update planner contract (Batch 4, first layer)

## Owner updates for changed Python sources (Batch 2)

`storage.build` first checks the immutable prior catalog and graph-site artifacts,
program/config/runtime/pins, compatible AST cache, source hashes, source-origin
schema, and the actual owner input ledger. A missing or incompatible new schema
uses a full cold build. Subsequent Python changes parse each changed file in
full and reuse unchanged AST object graphs from a source-verified JSON cache.
Jedi sees the complete captured source context. All execution owners in a
changed file start selected; downstream owners are selected from indexed B1
producer-to-consumer supports, same-container origin subscriptions, recorded
module reads and import requesters. A new direct slot writer resolves its
captured receiver before querying old same-origin readers. Unknown receivers,
opaque mutations and unverified inputs widen or fall back to full analysis.

`Graph.build(selected_owners=...)` only runs query, resolve, and adjudication
for selected execution owners. It retains old unknown/incomplete candidate
sites in the caller search; complete old sites owned by unselected functions
are indexed by their retained targets without requery. Multiple passes
reuse one captured Analyzer and Jedi project, resetting graph edges each pass;
metrics include cumulative executed queries, associations and pass count.
On a verified owner update, unchanged sites, edges, source supports,
subscriptions, write records, queries and input observations are rebound to
the new capture; selected owners replace their old records. The value-flow
sidecar is regenerated from current and verified retained read witnesses.
Origin evidence remains partial and never by itself proves whole-capture
semantic completeness. The full analyzer's `UNKNOWN`, provenance, certificate
and value-flow coverage rules remain authoritative. `simple_python.certify`
continues to compute compatible full-graph metadata and candidate policy; it
does not admit this owner update path.

`analysis_scope.mode=incremental-owners` reports selected and reused owner
counts, parsed changed files, reused sites/edges, complete context file count,
analysis passes, and actual cumulative query/association work. A failed owner
attempt reports its reason and separate preflight work before a full build.
The older strict/general source-certificate routes remain as compatibility
code; they are not a required gate for this path.

## Observed source origins (Batch 1)

Full graph analysis now writes private, source-located observations for ordinary
call targets, actual callback parameters, definition-time defaults, returned
values, and container reads and writes. Each support names a producer owner and
site, a consumer owner and site, a kind, status and location details. Parameter
supports are recorded when the analyzer actually resolves that parameter;
separate consuming call sites retain separate supports. A memoized getter's
container read is subscribed again for each final caller that consumes it.

`FileDependencies.unit_sources(owner, site=None, limit=100, max_bytes=100000)`
pages inspection results with `supports` and `has_more`. A row exceeding the
byte budget raises an error. `unit_readers(producer, site=None)` returns every
observed dependent owner/site through an indexed reverse lookup.
`unit_container_readers(origin, key)` returns **all** readers of that container
origin, marking `key_relation` as `same`, `range`, or `other-conservative`; it
does not exclude another key without a complete proof. `unit_container_writes`
without a key lists every known writer of the origin; its optional key selects
exact/range writes for inspection, not a complete invalidation closure. An
instance container origin includes the analyzer's existing unique constructor
allocation identity, so two unique instances do not share one origin. An
omitted key differs from the literal `None` key. `True`, `1`, and `1.0` share
one exact key identity; unsupported constant keys remain ranges.

The manifest declares `origin_dependency_schema=1` and
`origin_dependency_coverage=observed-source-supports-partial`. These records
retain candidates and `UNKNOWN`; they do not claim all Jedi or dynamic Python
inputs are enumerated and do not change full graph targets or precision. Old or
incompatible origin schemas raise an explicit source-origin error at this API.
Identical Python capture reuse copies the verified observations. The existing
strict/general changed-Python local routes mark origin evidence unavailable,
because they cannot yet merge a complete source ledger. Owner-level scheduling
will be integrated in a later batch; the public build gate remains the existing
source certificate policy in this batch.

## Function-value dependency design status

The private analysis dependency sidecar now writes schema 2 (schema 1 remains
readable for its original container-effect kind). It records **observed**
cross-module reads of known class members, function return bodies, matched
parameter callers and captured Jedi definition targets in addition to container
effects. `prepare` queries all these kinds through the producer-file index, and
checks retained records when merging a local component. Coverage stays `partial`:
future callers, absent names and broad Jedi observations have no complete
reverse witness. The whole-capture v6 syntax certificate and value-flow gate
remain mandatory; the partial ledger alone does not admit unsupported modules.
The separate closed-form v6 certificate and component policy admit the exact
three-file real-source fixture described below, while arbitrary business captures
still fall back. Schema 1 accepts only its original kind vocabulary; new kinds under schema 1
or unknown kinds under either schema fail sidecar validation.

An independent `analysis_input_schema=2` sidecar records the captured input
scope of actual Jedi queries, call-candidate enumeration, lexical lookup,
member lookup and ordinary resolve input: a validated v6 import component, or a single
capture-wide scope when that component proof is unavailable. The normalized
SQLite tables store scope, member and consumer rows; each consumer carries an
OR-ed purpose mask (1/2/4/8/16) without duplicating its scope members. The manifest carries only
`captured-analysis-scopes-partial`, counts and truncation. Schema 1 Jedi-only
rows remain readable with mask 1, but cannot authorize new local reuse. This is **not** a complete
Jedi read witness: it does not assert all internal, external or prospective
namespace reads. `prepare` queries indexed component members for a changed
file and seeds capture-scope consumers once, in addition to the existing schema
2 reads and writer watches. Missing/old/truncated scope evidence fails closed;
local reuse replaces selected consumers and checks retained scope boundaries.
No public graph kind or v6 syntax form changes.

For a separate 4B pilot, an unsupported whole-capture v6 change can reuse an unchanged
module whose frozen source has a `literal-functions-v1` proof and whose prior
semantic records are empty. The proof allows only a module docstring and unique
ordinary functions with passive literal returns or `pass`; the old strict v6
validator must also accept it. The build recomputes every other current Python
module, with the complete captured source and node catalog visible to Jedi.
When Jedi maps a captured definition whose AST was omitted, preparation expands
the selected set and retries. The private SQLite sidecar holds the source proof;
the manifest contains only its policy and count. Program/config/runtime/pin and
artifact integrity checks still apply. If no passive file can be retained, the
build uses the full graph. A strict-v6 local update preserves and rechecks these
proofs; a newly complex selected file can then enter the general route. When a
general candidate becomes a whole closed-v6 capture, it is rebuilt fully so
the fresh graph uses the certified import-component policy. This pilot does not certify arbitrary complex modules
for reuse, and `captured-analysis-scopes-partial` remains partial.

The [function-value dependency contract](FUNCTION_VALUE_DEPENDENCIES.md) remains a broader proposed design; the [gap audit](../review/batch4-incremental/FUNCTION_VALUE_GAP_AUDIT.md) preserves its earlier source baseline. A bounded `simple-python-v6` slice retains the v5 captured dictionary forms: straight-line module dictionary literals and writes with string keys, direct same-repository `from ... import registry`, module/function aliases, and direct known-key calls. It also admits annotations limited to exact unshadowed built-in scalar names or `None` (no forward strings), primitive literal **keyword-only** defaults (positional defaults still reject), straight-line ordinary self/constructor-rooted fields, exact external `dataclasses.dataclass(frozen=True, slots=True)` annotation-only classes with no methods, field defaults or factories, direct built-in `Exception` subclasses with exact `super().__init__`, and a passive self-field `@property`. It rejects dynamic/numeric keys, conditional or loop effects, escapes, unknown helper mutation, rebindings, arbitrary annotations/decorators/default factories/descriptors, unsupported imports and shadowed helpers. The analyzer still decides targets and `UNKNOWN`.

For a whole-capture validated v6 graph, candidate caller and constructor-site searches are scoped to undirected components of exact resolved captured top-level `from` imports. These closed forms have no other cross-module value bridge; an imported function may pass values, callbacks, constructors and fields in either direction within its component. External `re` and passive `dataclasses` remain explicit boundaries. The same validated policy applies when analyzing the selected local component; unsupported captures retain the original unrestricted searches. Import/layout/pin changes and old incompatible certificates still fall back through the existing whole-capture gate. The component policy affects analyzer candidate enumeration and its provenance, not persistence schema, public node kinds or value-flow coverage. This is not general per-unit witness coverage.

The v6 closed grammar also accepts explicit relative `from .module import name` and parent-level `from ..module import name` when the existing graph resolver normalizes the request to exactly one captured, selected provider with an AST and exact exported definition. Component edges and new-import closure use the same normalized request, so a changed caller pulls in a newly referenced provider and a changed provider selects its importer. Empty-module forms (`from . import name`), star imports, levels above the package root, missing or excluded providers, relative attempts to impersonate the external `dataclasses` helper, relative dictionary value-flow and arbitrary complex Python still fail closed. This retains `simple-python-v6`: previously certified shapes have the same semantics, and the existing program-hash compatibility gate requires a fresh full build for the changed implementation before local reuse.

The private `graph-sites.sqlite` sidecar has optional `value_flow_schema=1` container, entry, binding, write and read records. A missing entry has `present=false` and an exact subscription, not an asserted runtime dictionary key. `BINDS` connects source-identified aliases to one container, `ADDRESSES` the container to an entry, `WRITES`/`REACHES` supports to a read, and `USES_BINDING`/`READS`/`POSSIBLE_CALLS` link the read to its binding, entry and existing callable definition. These records are **not catalog/search/vector nodes**. The SQLite manifest reports compact counts, schema, coverage and `internal-sqlite-only` for this authoritative sidecar; that field is not the optional Neo4j publication status. Complete certified records can also be projected through `native-value-v3`, as described below and in [the Neo4j projection contract](NEO4J_FULL_GRAPH.md). The publication binding identifies the actual Neo4j projection schema and fingerprint. `FileDependencies` validates the sidecar and offers indexed exact-entry readers and bounded node/relation inspection. `python_incremental.prepare` consumes old entry subscribers, observed module readers and the one capture-wide writer-watch set alongside existing adjacency/import indexes. The broad watch can expand a real closure; it is not a key-precise performance guarantee. Old/missing/partial evidence, unsupported source shapes or incomplete analyzer witnesses fall back to full graph analysis. Identical-capture reuse copies records; local reuse replaces selected records and retains verified unrelated source records. This does not certify arbitrary dictionary or callback flow.

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
catalog and indexed graph evidence. The retained strict `simple-python-v4` subset accepts
only closed, explicit, absolute `from module import definition` relationships
and a narrow syntax for undecorated functions and ordinary classes. It excludes
inheritance, annotations, decorators, dynamic assignment, relative and star
imports (except the narrowly admitted `import re` below), unknown target namespaces, ambiguous modules within one repository,
and constructs whose receiver or effects cannot be certified. It is not a
general contract for real project code; the v6 closed-form extension above admits
the specific passive annotations, dataclass and property forms. The old snapshot must contain complete
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
remain unchanged. This strict subset certifies
the captured `item_units.py` leaf. The v6 closed-form extension additionally
certifies its `availability.py` and `errors.py` siblings; changing the delegated
availability argument in this exact three-file capture locally selects one file
and reuses two, matching an independent full build. An old predecessor without
the compatible current certificate falls back to full analysis.

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
analysis. The mixed v5 certificate now validates plain v4 callers against
the complete already-captured component context, so `A`'s dictionary,
`B`'s known-key reader, and ordinary `C`/`D` callers can be selected and
rebuilt together. It still validates each plain caller's body and exact
exported definition in the captured target AST, using the normal import/pin
resolver; an absent target, missing AST, registry escape or unsupported
provider falls back. This does not certify general dynamic callers.

Certified dictionary value evidence can now project into a separate
`native-value-v3` Neo4j scope during graph publication. Its value nodes,
edges and read subscriptions are fingerprint-bound and verified before the
complete marker. Old and partial sidecars stay on the four-field v2
projection, explicitly marked unprojected. SQLite remains the immutable
dependency authority; Neo4j only adds read-only traversal of existing
certified evidence and does not expand v5 admission.

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
