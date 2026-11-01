# PR-3 design: selected call facts feed callback and return analysis

Source inspected: `pr2-review1-fixed` at `1e265a9a6e087b87299940c6815f9957b8ceac37`. This is a read-only design, not an implementation or a PR-2 regression verdict. Follow `AGENTS.md`, the proposed function-value contract, the historical gap audit, and the repository-local code-graph procedure. The existing `pr3-composed-callback-baseline.log` records an actual full-build probe; no captured business code was executed.

## Reproducible gap and exact handoff

```python
def first(): pass
def execute(callback): callback()
R = {}
def register(key, fn): R[key] = fn
register('go', execute)
def run(): R['go'](first)
```

The full build records `run`'s `R['go']` call with selected target `execute` and `open-registry-writes`; the raw Jedi target is empty. The `execute` body's `callback` call has no target and `open-project-input`; raw Jedi is empty. Thus the finite registration/key source proves one selected *candidate* caller and its actual argument, while the callback's input inference cannot see it. Keep `open-registry-writes` and `open-project-input` according to their actual boundaries; the new `first` target will be partial where these reasons remain. This is a capability gap in the current source-to-caller handoff, not evidence that Jedi gave a wrong target.

`Analyzer._observe_query` populates `_site_position_targets` and `_site_targets` from raw Jedi observations, old unselected site seeds, and literal lambda identity. `prepare_site_queries` queries selected sites, with a narrow classmethod special case. `candidate_sites(function)` uses that index; an empty Jedi observation does not enter `execute`'s candidate set. `Graph.build` then processes public sites in inventory order, calling `tool_first_lexical`, `tool_first_subscript`, `resolve`, and `adjudicate`, but does not publish its selected result back to the caller index. `caller_atoms` separately resolves/adjudicates a candidate again; `may_call` admits only raw Jedi/classmethod/lambda even if the finite public selection proved it. A callback can be analyzed and memoized before a later registry call proves its caller. `resolve` memo keys are `(scope, id(expr), before)` and its `dependencies` records nested resolve calls, but an empty candidate set is not a nested resolve dependency; merely clearing the callback call memo is insufficient without a callee-candidate membership trigger.

## Minimum coherent change

1. Represent one in-capture call fact per actual site position: raw mapped Jedi atoms and original raw evidence, a distinct finite *selected* callable/class atom set with bound receiver/allocation metadata, unknown/completeness/proof and source-support references, plus literal lambda identity. Maintain `target -> site positions` and `site -> target atoms` indexes; replace the site's prior selected contribution by diff, never append stale targets. An old unselected site seed remains an already published observation, not a claim that its source was reanalyzed. Do not make an empty/unknown site a caller by spelling, function name, or per-function scan. Site positions/AST IDs are only in-capture; persisted support uses stable source and site identities.
2. Preserve Jedi's mapped definition as the primary signal and its no-result, failed mapping, external boundary, exception and `jedi-inference-not-exhaustive` evidence. Where Jedi has a mapped target, consume that target and do only necessary source/receiver/ordering evidence. Admit a supplemental finite target from the **same public adjudication** only when an actual source proof reaches that target (registration/key, lexical binding, argument, return, field/descriptor, etc.) under its coverage receipt. A selected target may coexist with unknown reasons. An unsupported guess or an unproved alternative does not become a caller. The existing `adjudicate` rules retain Jedi candidates unless a concrete semantic counterexample and applicable source/effect proof justify exclusion. Do not create a second target resolver solely for caller indexing.
3. Split target discovery from output projection. Prepare raw Jedi selected-owner observations once, then visit source-dependent sites at most once initially and publish newly adjudicated facts to the index. A changed target membership or bound metadata enqueues only that callee's parameter/default/receiver consumers and their actual downstream return/site dependents. Keep a reverse `callee -> parameter reads` link including previously empty candidate sets; it is a membership subscription, not a universe watch. It may be derived from the captured AST inventory and local resolution graph. For an owner-local update, use selected owners and verified retained site facts; do not resolve every unchanged site or every target. A source fact that first appears after an earlier callback site must re-evaluate that callback and its affected downstream consumers before final output.
4. Let `candidate_sites`, `may_call`, and `caller_atoms` consume the same indexed, adjudicated call fact. `caller_atoms` returns the selected matching atoms with bound metadata; if Jedi identifies a definition but omits receiver binding, attach only matching source-validated receiver metadata, keeping the raw target. Argument/keyword/default binding stays in `parameter`; its existing `actual-parameter`/`default-parameter` supports and unresolved unpacking handling remain. The caller index needs an explicit membership observation even when no match existed. Do not simply delete `may_call`'s guard while continuing to recompute in `caller_atoms`.
5. Make re-evaluation replace facts atomically for each affected consumer: memo/result and trace, resolve dependency edges, relevant source supports/subscriptions/writes, scope/input reads, call-site record and all projected CALLS/UNKNOWN/boundary edges. Invalidate reverse memo dependents of changed facts and the explicit parameter membership consumers; recompute until the affected facts reach a stable fingerprint including target atoms/bindings, reasons, completeness, proof/receipt and provenance. A prior unknown result must not be cached across a newly proved caller. Keep sibling supports when one source disappears. Bound cycles and budget exhaustion with existing explicit unknown/failure semantics; do not keep a stale 'resolved' result or silently publish a partial retry. Defer final Graph site/edge emission until the affected worklist settles, or regenerate only affected records from final facts. The current immediate append loop cannot be used unchanged.
6. Return resolution should use the same selected call fact for `expr.func` when obtaining callable bodies; preserve `return-value` support from returned expression to consuming call, and subscribe to callable-return membership even when the return has no known target. A `factory()` or getter returning an `execute` callable should feed its subsequent invocation fact, then `execute`'s parameter, then its callback. The target selection and source association must remain separate responsibilities. Treat return expressions, nested closure cells, bound methods, decorators, context phases and dynamic boundaries under their existing semantics; do not claim general Python execution fidelity.

Illustrative scheduling (not a request for a whole-capture repeated site pass):

```text
prepare_raw_queries(selected_owners)                    # one selected-owner inventory pass
enqueue_selected_site_sources_once()
while affected_queue:
    consumer = pop()
    new = evaluate_using_current_site_facts(consumer)
    changed = replace_and_diff(old_fact[consumer], new)
    enqueue(reverse_resolve_dependents(changed))
    enqueue(callee_parameter_membership_readers(changed.site_target_diff))
    enqueue(return_and_site_consumers(changed))
project_final_sites_edges_and_supports()
```

The resolver may discover a site while answering another site; guard reentry and record the dependency, then let the worklist revisit after the new fact. A one-shot prepass without invalidation fails when `callback` is memoized before `R['go']` resolves. Repeating all sites to a fixed point is equally unsuitable. Fact replacement and deterministic queue order matter when a source is removed or Jedi and finite alternatives differ.

## Gates and probes

* Full build: probe above; assert `run` selects `execute`, `execute.callback` includes `first`, the honest unknown reasons remain, actual-parameter and registration/container/target support chain exists, raw Jedi evidence remains unchanged. Assert a separate `R2['go']` and unrelated unknown `execute(...)` spelling do not join this caller. Test two independent registrations and removal of one support without erasing the other.
* Order/caching: sources arranged so callback is first in site inventory, then caller; reverse order; `first -> second -> first` callback replacement; a getter/return chain and an alias of `R`; bound method receiver, positional/keyword/default and an unknown unpacking boundary. Compare with a fresh full build including site fields, completeness, unresolved reasons, edges and provenance, not target names alone.
* Local update: altered registry writer/entry, new formerly missing key, deleted writer, changed callback function and changed returned callable; compare immutable old view and updated result with independent full build. Require old negative/entry subscriptions, producer supports and existing input/scope readers to seed selected owners. A change crossing unsupported old evidence fails without changing current publication; never use whole-capture reanalysis as ordinary fallback.
* Locality: count initial source inventory, Jedi query entries/cache hits/actual executions, selected source visits, index lookups, changed fact evaluations, internal support reads and required output serialization separately. With unrelated functions, unknown sites, registries and writers scaled up, show per-changed-function target/member lookups bounded by indexed actual relationships. The full initial preparation may still be O(all selected sites); a local change must not add per-function unknown scans or repeat all sites. Respect the existing 20,000 association cap.

No implementation or tests were changed in this design pass. PR-2's independent definition-header repair should pass its gate before this refactor starts. This design does not authorize a schema migration, changed provider/pins, source execution, Neo4j, budget increase, or a push.
