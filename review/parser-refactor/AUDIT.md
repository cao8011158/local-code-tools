# Whole-parser capability and responsibility audit

Source baseline60085dc0158d6ae26b21dfabddafa0d6b5ef9a3b, Jedi0.20.1/Parso0.8.7/Python3.12. User authorized audit followed by evidence-based refactor, including former CW-01 scope. Root inspected all lct modules touching Python inference/dependency maintenance; developer independently ran13 directJedi/Graph cases. This is architectural and bounded empirical coverage, not proof of all Python or a completed refactor.

## Actual integration and responsibilities

| Area | Present implementation and Jedi use | Audit conclusion and migration boundary |
| --- | --- | --- |
| Captured input/project | Analyzer.__init__ mounts captured sources, constructs per-repository Jedi.Project with explicit src/dependency sys_path, smart_sys_path=False, load_unsafe_extensions=False | Necessary integration; do not substitute current working tree or execute business modules. No missing-source failure treated asJedi bug. |
| Definition catalog/site phases | extract.python_nodes + Analyzer.inventory/EffectCatalog | Necessary module/class/function/site identities and body/default/decorator phase records; not duplicate target inference. |
| API and mapping | Analyzer.query usesinfer atcallee endtoken; gotofollow_imports forbindings; map_name exact captured file/line/column indexes, boundary and pin checks | Actual tool use exists. Ordinary infer mapped results surviveJD1. Statement mapping may recursively callself.resolve and needs separate analysis. Both raw and mapped output matter. |
| Names/imports/aliases | resolveName->name/reaching/binding; imports alsogoto | Tool already resolves tested direct/alias/conditional targets. Local binding walks still recompute candidates. Need keep source lookup, import namespace/negative membership and provenunbound/deleted rule; stop using a second target derivation for fully tool-covered cases. |
| Parameters/defaults | parameter enumerates observed indexed callers, maps positional/keyword/default, recursivelyresolve arguments | Jedi resolves tested callback/default targets. Actual-parameter/default source supports and caller dependency needed; they do not justify recomputing every argument target. Receiver offset and caller-specific metadata must remain. |
| Returns/closures | resolveCall->localcallee->return_values->recursive resolve; closure timing in ReceiverAccess | Jedi resolves tested returned callable; output-to-consumer support and closure invocation timing are domain requirements. Test-bound exception paths remain until replaced with equivalent source collection. |
| Containers | subscript resolvesorigin, container_slots reconstructsvalues/writes, registry_arguments followscallback inputs, subscriptions/supports persisted | Basic literal/update/key lookup covered byJedi. Registered global dict mutation has actualmissing result, so minimal source supplement needed. Global fallbackwriter enumeration not justified by tool-known literaltarget. Source origin/key/write/read must remain precise and supportnew/deletedwriters. |
| Methods/fields/descriptors | attribute/member/instance_field/field_scope/call_field_effect + ReceiverAccess thenadjudicate | Jedi covers ordinarymethod/constructorfield probes. Corpus has real allocation, orderedfieldreplacement/delete/classfallback andclassmethod conflicts with explicit counterexamples; do not globallytrust one returnedcandidate ascomplete or erase required refinements. Index/sourcecollection and selectiveexceptions must replace unconditional simulation. |
| Decorators/context/deferred bodies | context_wrapper goto, generator_binding, binding classification, inventoryphase | Jedi already returns actualwrapper in simpledecorator probe; custom UNKNOWN must not discardit. Generator creation vsresumption, context entry andcapturedphase are domainrecords not baredefinition inference. |
| Selection policy | Graph.build alwaysquery->resolve->adjudicate; caller_atoms likewise; references/base/context alsoresolve | Central architecturalduplication, not isolated containerbug. Introduce explicit tool-backed target resolution and separate source/effect needs with concreteexceptions. Simply renaming functions will not remove work. |
| Uncertainty | query adds jedi-inference-not-exhaustive toall non-goto callable/class/instance results | LCT policy, not rawJedi statement. Completeness/unsupportedsemantics should be explicit; audit blanketpolicy separately. Do not silently markcomplete from rawtarget. |
| Source/dependency ledger | unit_support, unit_write, unit_subscribe, analysisread/watch/input records | Needed forincremental selection; successful, absent andfuturekey dependencies distinct. Reuse target observations to filldata; do notdelete these toreduceCPU. |
| Incremental/storage/query | unit_incremental directionalindexed closure, selectedownerGraph, immutable versions, sidecar/SQLintegrity, queryindexedlookups | ResponsibilitiesJedi doesn'treplace. Preservehash-basedupdate selection, oldevidence afterdeletion, caches/version compatibility andfailedpublication; not targets for wholesale removal. Legacy simple_python remains compatibilityshape metadata, not restoredglobaladmission. |
| Value flow/projection | value_flow emits domainnodes/evidence; Neo4joptionalprojection; embedding/search existingcatalog | Persistence/projection not coretargetinference. No new vectors/services/schema justforrefactor. |

## Independent current-corpus observations

Root wrapped realGraph.build without changing target computation and ran existing pipeline/call-access/review3/review4/regression/effect/core tests: **343 passed,1 skipped,22.03s,exit0**.802 site observations across thosefixtures, not802 uniqueproductioncalls and not a realprojecttime percentage. Full raw mappedJedi/local/selected decisions in decision-matrix.json; originallog decision-matrix.log; harness preservedas decision_matrix.py.

-581 knownJedi+knownlocal matchingtargets: demonstrable overlap in thissample, not proofthat all their provenance can be skipped.
-51 tested-semantic-rule differingdecisions (4 localempty,47 localnonempty), includinglocalunbound, classmethodreceiver, orderedfieldmutation/deletion andinstanceisolation. These need preciseexceptions andsourceproof, not indiscriminate removal.
-39 localtargets withoutmappedJeditarget: registryeffects, constructor/classmethodbinding, lambdas andcontextfactory cases. Missingraw vs mappingboundary must remain distinguished in eachrow.
-Otherpartialconflicts preserve rawtarget andexplicitgaps underJD1;102 both-targetempty matchingcases remainunknown/noncallable asrecorded.

Root actualcontainerprobealreadyprovedbeforethisstep: querymappedfirst beforecontainer_slots;0/100 unrelatedprivatewriters still2/102scopes checked andsamefirstselected. Tooltargetpreserved, redundantreconstruction remains. Developer13-caseprobe corroborateswidecapability; its rawcasecontexts andlimitations are in DEVELOPER_AUDIT.md.

## Implementation sequence

PR-1: explicit tool-backed target/source separation for direct lexical calls/aliases, with independent no-second-target-walk controls; preserve tested unbound/deleted/receiver/context exceptions and allsource/invalidation semantics. No project-level syntaxadmissiongate.

PR-2: container target observation plus exact origin/write/read sourcecollection; remove perread unrelatedwriterenumeration. Reuse documentedJedi binding/reference capability only where actualprobe provesit. Globalregisteredcallbackgaps getminimal supportedassociation; no blanketUNKNOWN->allfunctions/scopes. Keep aliases/keys/futurewriter/deletion andcrossfileparameter/getterreturns.

PR-3: migrate callbacks/returns andmethods/fieldsourceeffects where corpusproves overlap; centralize sharedobservations andtargetedexceptions; remove replacedlegacycode andunneededblanketpolicy. Runwhole783controls andnewnegative/localitycases, current-runtime ninepubliclifecycle andcomplete83cold+continuouswarm/query/oldview/failureacceptance. Profileifstillblocked, do notblindlyraisebudget/timeouts. Batchboundaries may refinebasedonimplementationevidence; no promises everyunknown canbe solved.

Official contract consulted: https://jedi.readthedocs.io/en/latest/docs/api.html (initialfetchfailed, installed0.20.1APIdocstrings/source available), https://jedi.readthedocs.io/en/latest/docs/features.html and https://jedi.readthedocs.io/en/latest/docs/development.html (historicalinternals explicitlywarnage; no unsupportedinternalAPI is added). Useactualversiondirectprobes asfiniteevidence.
