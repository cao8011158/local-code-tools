"""Certified local graph preparation for a small, closed Python subset."""

import ast
import json
import sqlite3
from collections import deque
from contextlib import closing

from . import extract as extraction
from . import python_analysis
from . import analysis_inputs
from . import passive_python
from .common import canonical, digest
from .evidence_reuse import EvidenceReuseRejected, RebindContext
from .extract import definition_version, extract, module_name
from .graph import Graph
from .python_analysis import RequiredAnalysisContext
from .simple_python import CERTIFICATE, certify

_PASSIVE_NODE_QUERY = ("select node_id from nodes where repository=? "
                       "and kind in ('module','function') and path=?")


def merge_analysis_dependencies(old_reads, old_watches, new_reads, new_watches, *,
                                selected, old_nodes, new_nodes, verified,
                                old_truncated=False, new_truncated=False):
    """Replace selected consumers' records without trusting missing endpoints.

    This is only sidecar maintenance. Its partial result is never an admission
    certificate or a substitute for the existing syntax/closure gate.
    """
    if old_truncated or new_truncated:
        return None, "previous-analysis-dependency-evidence-unavailable"

    def owner(ident):
        node = old_nodes.get(ident)
        return (node["repository"], node["path"]) if node else None

    reads = set(new_reads)
    watches = set(new_watches)
    for consumer, producer, kind in old_reads:
        if owner(consumer) in selected:
            continue
        if owner(producer) in selected:
            return None, "old-analysis-read-crosses-selected-boundary"
        if (owner(consumer) not in verified or consumer not in new_nodes or
                producer not in new_nodes or new_nodes[consumer]["kind"] != "module" or
                new_nodes[producer]["kind"] != "module"):
            return None, "old-analysis-read-endpoint-unavailable"
        reads.add((consumer, producer, kind))
    for consumer, kind, universe in old_watches:
        if owner(consumer) in selected:
            continue
        if selected and universe == "all-captured-python":
            return None, "old-analysis-watch-crosses-selected-boundary"
        if (owner(consumer) not in verified or consumer not in new_nodes or
                new_nodes[consumer]["kind"] != "module"):
            return None, "old-analysis-watch-consumer-unavailable"
        watches.add((consumer, kind, universe))
    if len(reads) + len(watches) > python_analysis.ANALYSIS_DEPENDENCY_LIMIT:
        return None, "combined-analysis-dependency-budget-uncertified"
    return (sorted(reads), sorted(watches)), None


def _passive_empty(folder, proofs):
    """Verify old passive source proof has no nonlexical semantic facts."""
    if not proofs:
        return set()
    with closing(sqlite3.connect((folder / "catalog.sqlite").as_uri() +
                                 "?mode=ro&immutable=1", uri=True)) as catalog, closing(
            sqlite3.connect((folder / "graph-sites.sqlite").as_uri() +
                            "?mode=ro&immutable=1", uri=True)) as evidence:
        owner = {}
        bad = set()
        for repo, path in proofs:
            found = [row[0] for row in catalog.execute(_PASSIVE_NODE_QUERY, (repo, path))]
            if not found:
                bad.add((repo, path))
            owner.update((ident, (repo, path)) for ident in found)
        for source, target in catalog.execute(
                "select source,target from edges where kind!='CONTAINS'"):
            bad.update(key for ident in (source, target) if (key := owner.get(ident)))
        for table, column in (("sites", "execution_owner"),
                              ("query_observations", "key"),
                              ("import_dependencies", "source_module"),
                              ("import_requests", "source_module"),
                              ("value_nodes", "module")):
            for (raw,) in evidence.execute(f"select data from {table}"):
                ident = json.loads(raw)[column]
                if column == "key":
                    ident = ident[0]
                if ident in owner:
                    bad.add(owner[ident])
        for consumer, producer in evidence.execute(
                "select consumer_module,producer_module from analysis_reads"):
            bad.update(key for ident in (consumer, producer) if (key := owner.get(ident)))
        for table, field in (("analysis_watches", "consumer_module"),
                             ("analysis_input_consumers", "module_id"),
                             ("analysis_input_members", "module_id")):
            for (ident,) in evidence.execute(f"select {field} from {table}"):
                if ident in owner:
                    bad.add(owner[ident])
        bad.update((r, p) for r, p in evidence.execute(
            "select consumer_repository,consumer_path from value_reads") if (r, p) in proofs)
    return set(proofs) - bad


def prepare(folder, prior, files, repos, *, dependencies, graph_sites, attempts=None,
            general=False, forced=None, parsed_cache=None):
    """Return (nodes, edges, graph, metrics) or (None, reason)."""
    if not general and prior.get("simple_python_certificate") != CERTIFICATE:
        return None, "previous-simple-python-certificate-unavailable"
    if not general and (prior.get("value_flow_schema") != 1 or
            prior.get("value_flow_coverage") != "certified-dictionary-v1"):
        return None, "previous-value-flow-evidence-unavailable"
    if general and (prior.get("passive_python_schema") != 1 or
                    prior.get("passive_python_policy") != passive_python.POLICY or
                    not dependencies.passive_available):
        return None, "previous-passive-source-evidence-unavailable"
    if prior.get("analysis_dependency_schema") not in (1, 2) or prior.get("analysis_dependency_truncated"):
        return None, "previous-analysis-dependency-evidence-unavailable"
    if (prior.get("analysis_input_schema") != analysis_inputs.SCHEMA or
            prior.get("analysis_input_coverage") != analysis_inputs.COVERAGE or
            prior.get("analysis_input_truncated") or
            not dependencies.input_scope_available):
        return None, "previous-analysis-input-evidence-unavailable"
    if prior["graph"].get("analysis_limited"):
        return None, "previous-association-budget-limited"
    prior_bound = prior["graph"].get("association_bound")
    if not isinstance(prior_bound, int) or not 0 <= prior_bound <= 20000:
        return None, "previous-association-bound-unavailable"
    python = {(f["repository"], f["path"]): f for f in files if f["path"].endswith(".py")}
    if not python:
        return None, "no-python-modules"
    # The graph's existing local-first, exact-pin resolver is the only authority
    # for imports. Module identities do not require parsing unchanged ASTs.
    module_catalog = [dict(node_id=f"{repo}:{path}:module:{module_name(path)}#1",
                           kind="module", repository=repo, path=path,
                           qualname=module_name(path)) for repo, path in python]
    resolver = Graph(module_catalog, {}, repos)
    if any(len(ids) != 1 for ids in resolver.modules.values()):
        return None, "ambiguous-module-name"
    def package_context(repository, name):
        """Locate only captured modules along one actual dotted import path."""
        parts = name.split(".")
        return {(resolver.nodes[ident]["repository"], resolver.nodes[ident]["path"])
                for size in range(1, len(parts) + 1)
                for ident in resolver.modules.get((repository, ".".join(parts[:size])), ())}
    if resolver.cross_bindings != prior["graph"].get("dependency_bindings"):
        return None, "dependency-bindings-changed"
    snapshots = {name: digest(canonical(sorted((f["path"], digest(f["text"]))
                                            for f in files if f["repository"] == name)))
                 for name in {f["repository"] for f in files}}
    decoded_hashes = {(f["repository"], f["path"]): digest(f["text"]) for f in files}
    with closing(sqlite3.connect((folder / "catalog.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        old_files = {(r, p): (sha, source) for r, p, sha, source in db.execute(
            "select repository,path,sha256,text from files")}
        if {key: sha for key, (sha, _) in old_files.items() if not key[1].endswith('.py')} != {
                (f["repository"], f["path"]): f["sha256"] for f in files
                if not f["path"].endswith('.py')}:
            return None, "document-or-other-input-changed"
        changed = {key for key in python.keys() | {k for k in old_files if k[1].endswith('.py')}
                   if key not in python or key not in old_files or old_files[key][0] != python[key]["sha256"]}
        if not changed:
            return None, "no-python-source-change"
        # A package initializer can shadow every dotted child import of a
        # dependency; exact requested-module indexes cannot certify that set.
        if any(path == "__init__.py" or path.endswith("/__init__.py")
               for _, path in changed):
            return None, "package-initializer-changed"
        if any((key not in python or key not in old_files)
               and dependencies.has_descendant_requesters(key[0], module_name(key[1]))
               for key in changed):
            return None, "ancestor-module-layout-changed"
        if general and any(module_name(path).split(".")[0] in {"re", "dataclasses"}
                           for _, path in changed):
            return None, "stdlib-helper-shadow-layout-changed"
        passive_retained = set()
        if general:
            proofs = dependencies.passive_sources()
            candidate_passive = {key: sha for key, sha in proofs.items()
                                 if key in python and key not in changed and
                                 key in old_files and old_files[key][0] == sha == python[key]["sha256"]}
            passive_retained = _passive_empty(folder, candidate_passive)
            if not passive_retained:
                return None, "no-verified-passive-reuse"
        # Strict mode relies on the old whole-capture certificate. General mode
        # selects every complex file and retains only verified passive files.
        selected = (set(changed) | (python.keys() - passive_retained) if general
                    else set(changed)) | set(forced or ())
        queue = deque(sorted(selected))
        # The global watch is one immutable old-capture subscription. Fetch it
        # once, not for each selected module in the worklist.
        for watcher in dependencies.analysis_watchers("slot-writer-universe"):
            if watcher not in selected:
                selected.add(watcher)
                queue.append(watcher)
        for watcher in dependencies.input_scope_watchers():
            if watcher not in selected:
                selected.add(watcher)
                queue.append(watcher)
        parsed = parsed_cache if parsed_cache is not None else {}
        while queue:
            key = queue.popleft()
            candidates = dependencies.adjacent(*key)
            # Use the old exact entry subscriptions, including reads of absent
            # keys; old evidence is indispensable after a write is deleted.
            if dependencies.value_flow_complete:
                for entry in dependencies.entry_ids_for_file(*key):
                    candidates.update(dependencies.value_readers(entry))
            candidates.update(dependencies.analysis_readers(*key))
            candidates.update(dependencies.input_scope_readers(*key))
            # Existing analyzer watch coverage was seeded once above; this
            # broad fanout is deliberately retained for semantic safety.
            if key[1].endswith(".py"):
                candidates.update(dependencies.importers(key[0], module_name(key[1])))
                if key in changed:
                    candidates.update(dependencies.requesters(key[0], module_name(key[1])))
            if key in python:
                if key not in parsed:
                    parsed[key] = extraction.python_nodes(dict(
                        python[key], snapshot_id=snapshots[key[0]]))
                    if attempts is not None:
                        attempts["python_files_parsed"] += 1
                tree = parsed[key][1][f"{key[0]}:{key[1]}:module:{module_name(key[1])}#1"]
                candidates.update(package_context(key[0], module_name(key[1])))
                for stmt in tree.body:
                    if isinstance(stmt, ast.ImportFrom) and stmt.module and stmt.names:
                        module_id = f"{key[0]}:{key[1]}:module:{module_name(key[1])}#1"
                        request = resolver.import_request_module(module_id, stmt, stmt.names[0])
                        if request is None:
                            continue  # Selected syntax certification rejects invalid levels.
                        # Jedi also observes local package/module ancestors,
                        # even when the exact target is a pinned provider.
                        candidates.update(package_context(key[0], request))
                        for ident in resolver.imported(key[0], request):
                            target = resolver.nodes.get(ident)
                            if target is not None:
                                candidates.add((target["repository"], target["path"]))
                                candidates.update(package_context(target["repository"],
                                                                  target["qualname"]))
            for candidate in candidates:
                if candidate is not None and candidate not in selected:
                    selected.add(candidate)
                    queue.append(candidate)
        selected_present = selected & python.keys()
        if general and not selected_present:
            return None, "general-to-whole-v6-rebuild"
        # Strict mode certifies selected ASTs. General mode analyzes every
        # selected complex source and uses the passive source/empty-fact proof.
        selected_files = [python[k] for k in sorted(selected_present)]
        local_nodes, local_asts = [], {}
        for key in sorted(selected_present):
            if key not in parsed:
                parsed[key] = extraction.python_nodes(dict(
                    python[key], snapshot_id=snapshots[key[0]]))
                if attempts is not None:
                    attempts["python_files_parsed"] += 1
            ns, trees = parsed[key]
            local_nodes.extend(ns)
            local_asts.update(trees)
        # The resolver has the complete captured module catalog; selected ASTs
        # come only from parsed files, with general mode expanding on demand.
        if not general and certify(selected_files, local_asts, graph=resolver) != CERTIFICATE:
            return None, "selected-python-syntax-unsupported"
        if general and certify(selected_files, local_asts, graph=resolver) == CERTIFICATE:
            # Retained passive files are strict-v6 and have no imports. A full
            # closed capture needs the v6 component policy on both oracle and
            # candidate, so rebuild rather than analyze it with missing ASTs.
            return None, "general-to-whole-v6-rebuild"
        with closing(sqlite3.connect((folder / graph_sites).as_uri() + "?mode=ro&immutable=1", uri=True)) as evidence:
            try:
                certified = {(r, p): sha for r, p, sha in evidence.execute(
                    "select repository,path,sha256 from simple_python_certificates")}
            except sqlite3.Error:
                return None, "old-syntax-certificates-unavailable"
            old_python = {key: item[0] for key, item in old_files.items()
                          if key[1].endswith(".py")}
            if not general and certified != old_python:
                return None, "old-syntax-certificates-incomplete"
            old_order = [nid for (nid,) in evidence.execute("select node_id from node_order order by ordinal")]
            old_sites = [json.loads(raw) for (raw,) in evidence.execute("select data from sites order by ordinal")]
            old_observations = [json.loads(raw) for (raw,) in evidence.execute("select data from query_observations order by key")]
            old_deps = [json.loads(raw) for (raw,) in evidence.execute("select data from import_dependencies order by ordinal")]
            old_requests = [json.loads(raw) for (raw,) in evidence.execute("select data from import_requests order by ordinal")]
            old_analysis_reads = list(evidence.execute(
                "select consumer_module,producer_module,kind from analysis_reads"))
            old_analysis_watches = list(evidence.execute(
                "select consumer_module,kind,universe from analysis_watches"))
            old_input_payload = analysis_inputs.read(evidence, schema=analysis_inputs.SCHEMA)
            old_input_payload["truncated"] = prior["analysis_input_truncated"]
            old_value_nodes = [json.loads(raw) for (raw,) in evidence.execute(
                "select data from value_nodes")]
            old_value_edges = [dict(source=s, target=t, kind=k) for s, t, k in evidence.execute(
                "select source,target,kind from value_edges")]
            old_value_reads = [dict(entry=e, read=r, consumer_repository=cr,
                                    consumer_path=cp) for e, r, cr, cp in evidence.execute(
                "select entry,read,consumer_repository,consumer_path from value_reads")]
        old_nodes = {nid: json.loads(raw) for nid, raw in db.execute("select node_id,data from nodes")}
        old_edges = [json.loads(raw) for (raw,) in db.execute("select data from edges")]
    if len(old_order) != len(old_nodes) or any(nid not in old_nodes for nid in old_order):
        return None, "old-node-order-invalid"
    if any(key not in old_files or old_files[key][0] != f["sha256"] or
           digest(old_files[key][1]) != decoded_hashes[key]
           for key, f in python.items() if key not in changed):
        return None, "unchanged-source-proof-failed"
    # Re-run the exact extractor's capture digest and definition identity logic.
    document_nodes, _ = extract([f for f in files if not f["path"].endswith(".py")])
    documents = {(n["repository"], n["path"]): [] for n in document_nodes if n["path"]}
    for n in document_nodes:
        if n["path"]:
            documents[n["repository"], n["path"]].append(n)
    nodes = []
    for name in sorted(snapshots):
        nodes.append(dict(node_id=f"{name}::repository", repository=name, path="",
                          kind="repository", qualname=name, parent=None, start=0, end=0,
                          signature="", docstring="", brief="", fingerprint=digest(name),
                          is_test=False))
    by_old_file = {}
    for nid in old_order:
        n = old_nodes[nid]
        by_old_file.setdefault((n["repository"], n["path"]), []).append(n)
    by_new_file = {}
    for n in local_nodes:
        if n["path"]:
            by_new_file.setdefault((n["repository"], n["path"]), []).append(n)
    verified = {}
    for f in files:
        key = f["repository"], f["path"]
        if key in python:
            if key in selected_present:
                nodes.extend(by_new_file.get(key, ()))
            else:
                old = by_old_file.get(key, ())
                if not old or old[0]["kind"] != "module":
                    return None, "old-module-catalog-unavailable"
                for original in old:
                    n = dict(original)
                    if (n.get("source_sha256") != decoded_hashes[key]
                            or n.get("file_fingerprint") != f["sha256"]):
                        return None, "old-source-catalog-mismatch"
                    n["snapshot_id"] = snapshots[f["repository"]]
                    n["version_id"] = definition_version(n)
                    nodes.append(n)
                verified[key] = (digest(old_files[key][1]), decoded_hashes[key])
        else:
            nodes.extend(documents.get(key, ()))
    byid = {n["node_id"]: n for n in nodes}
    if len(byid) != len(nodes):
        return None, "new-node-identity-collision"
    # An import added in a selected module can pull in an unchanged target;
    # the bounded graph must see every selected target and no outside module.
    selected_graph_nodes = (nodes if general else [n for n in nodes if n["kind"] == "repository"
                            or (n["repository"], n["path"]) in selected_present])
    graph = Graph(selected_graph_nodes, local_asts, repos)
    full_graph = Graph(nodes, {}, repos)
    if graph.cross_bindings != prior["graph"].get("dependency_bindings"):
        return None, "dependency-bindings-changed"
    source_context = ({f"{r}:{p}:module:{module_name(p)}#1": f["text"]
                       for (r, p), f in python.items()} if general else None)
    try:
        local_edges, info = graph.build(source_context=source_context)
    except RequiredAnalysisContext as required:
        key = required.repository, required.path
        if not general or key not in python or key in selected_present:
            return None, "required-analysis-context-unavailable"
        return prepare(folder, prior, files, repos, dependencies=dependencies,
                       graph_sites=graph_sites, attempts=attempts, general=True,
                       forced=set(forced or ()) | {key}, parsed_cache=parsed)
    local_flow = info.get("_value_flow")
    if local_flow is None or not general and not local_flow["complete"]:
        return None, "local-value-flow-witness-incomplete"
    if info["analysis_limited"]:
        return None, "local-association-budget-limited"
    if (prior_bound + info["association_evaluations"] > 20000 and not general):
        return None, "combined-association-budget-uncertified"
    info["association_bound"] = (info["association_evaluations"] if general else
                                 prior_bound + info["association_evaluations"])
    context = RebindContext(old_nodes=old_nodes, new_nodes=byid, old_trees={},
                            new_trees={}, selected_paths=selected,
                            verified_sources=verified)
    def owner_key(ident):
        n = old_nodes.get(ident)
        return (n["repository"], n["path"]) if n else None
    try:
        site_ids = {}
        reused_sites = []
        for site in old_sites:
            owner = owner_key(site["execution_owner"])
            if owner in selected:
                continue
            if owner not in verified:
                return None, "old-site-owner-unsupported"
            updated = context.rebind(site, owner_id=site["execution_owner"])
            module = byid[site["execution_owner"]]["module"]
            source = byid[module]
            updated["site_id"] = digest(canonical([
                source["repository"], source["path"], source["snapshot_id"],
                site["line"], site["column"], site["end_line"],
                site["end_column"], site["kind"],
            ]))
            site_ids[site["site_id"]] = updated["site_id"]
            reused_sites.append(updated)
        edges = []
        for e in old_edges:
            source, target = owner_key(e["source"]), owner_key(e["target"])
            if e["kind"] == "CONTAINS":
                continue
            if source in selected or target in selected:
                continue
            if source and source[1] and source not in verified:
                return None, "old-edge-source-unsupported"
            updated = dict(e)
            updated.pop("edge_id")
            if "site_id" in updated:
                updated["site_id"] = site_ids[updated["site_id"]]
            updated["source_version_id"] = byid.get(e["source"], {}).get("version_id")
            updated["target_version_id"] = byid.get(e["target"], {}).get("version_id")
            updated["edge_id"] = digest(canonical(updated))
            edges.append(updated)
        reused_edge_count = len(edges)
        for n in nodes:
            if n["parent"] and (n["repository"], n["path"]) not in selected_present:
                full_graph.add_edge(n["parent"], n["node_id"], "CONTAINS", "resolved",
                               "AST lexical ownership", n["start"], n.get("column", 0))
        edges.extend(local_edges)
        edges.extend(full_graph.edges)
        def retained(records, key):
            return [r for r in records if owner_key(r[key]) not in selected]
        observations = []
        for record in old_observations:
            if owner_key(record["key"][0]) not in selected:
                observations.append(context.rebind(record, owner_id=record["key"][0]))
        observations.extend(info.pop("_query_observations"))
        deps = retained(old_deps, "source_module") + info.pop("_import_dependencies")
        requests = retained(old_requests, "source_module") + info.pop("_import_requests")
        merged, reason = merge_analysis_dependencies(
            old_analysis_reads, old_analysis_watches,
            info.pop("_analysis_reads"), info.pop("_analysis_watches"),
            selected=selected, old_nodes=old_nodes, new_nodes=byid, verified=verified,
            old_truncated=prior["analysis_dependency_truncated"],
            new_truncated=info.pop("_analysis_dependency_truncated"))
        if merged is None:
            return None, reason
        analysis_reads, analysis_watches = merged
        input_payload = analysis_inputs.merge(
            old_input_payload, info.pop("_analysis_inputs"), selected=selected,
            old_nodes=old_nodes, new_nodes=byid, verified=verified)
        if input_payload is None:
            return None, "old-analysis-input-crosses-selected-boundary"
        retained_nodes = []
        for record in old_value_nodes:
            owner = owner_key(record["module"])
            if owner in selected:
                continue
            if owner not in verified:
                return None, "old-value-flow-owner-unverified"
            updated = dict(record)
            if "site_id" in updated:
                if updated["site_id"] not in site_ids:
                    return None, "old-value-flow-site-unavailable"
                updated["site_id"] = site_ids[updated["site_id"]]
            retained_nodes.append(updated)
        retained_ids = {record["id"] for record in retained_nodes}
        old_ids = {record["id"] for record in old_value_nodes}
        retained_edges = []
        for record in old_value_edges:
            source, target = record["source"], record["target"]
            if source in retained_ids:
                if target in old_ids and target not in retained_ids:
                    return None, "old-value-flow-crosses-selected-boundary"
                if target in old_nodes and owner_key(target) in selected:
                    return None, "old-value-flow-target-selected"
                retained_edges.append(record)
            elif source not in old_ids:
                return None, "old-value-flow-source-unavailable"
        retained_reads = []
        for record in old_value_reads:
            if record["read"] in retained_ids:
                if record["entry"] not in retained_ids:
                    return None, "old-value-flow-read-crosses-selected-boundary"
                retained_reads.append(record)
        local_flow = dict(nodes=retained_nodes + local_flow["nodes"],
                          edges=retained_edges + local_flow["edges"],
                          reads=retained_reads + local_flow["reads"],
                          complete=(local_flow["complete"] if general else True))
        if (len(local_flow["nodes"]) + len(local_flow["edges"]) +
                len(local_flow["reads"]) > python_analysis.ANALYSIS_DEPENDENCY_LIMIT):
            return None, "combined-value-flow-budget-uncertified"
    except (EvidenceReuseRejected, KeyError, TypeError, ValueError):
        return None, "old-evidence-rebind-uncertified"
    sites_by_file = {}
    for site in reused_sites + info["sites"]:
        owner = byid[site["execution_owner"]]
        sites_by_file.setdefault((owner["repository"], owner["path"]), []).append(site)
    info["sites"] = [site for f in files
                     for site in sites_by_file.get((f["repository"], f["path"]), ())]
    info["call_sites"] = len(info["sites"])
    info["_query_observations"] = observations
    info["_import_dependencies"] = deps
    info["_import_requests"] = requests
    info["_analysis_reads"] = analysis_reads
    info["_analysis_watches"] = analysis_watches
    info["_analysis_inputs"] = input_payload
    retained_proofs = []
    for key, sha in dependencies.passive_sources().items() if dependencies.passive_available else ():
        if key in selected:
            continue
        if (key not in verified or key not in python or key not in old_files or
                old_files[key][0] != sha or python[key]["sha256"] != sha):
            return None, "old-passive-source-proof-unavailable"
        retained_proofs.append(dict(repository=key[0], path=key[1], sha256=sha,
                                    policy=passive_python.POLICY))
    selected_proofs = [proof for f in selected_files
                       if (proof := passive_python.certify(f, local_asts.get(
                           f"{f['repository']}:{f['path']}:module:{module_name(f['path'])}#1")))]
    info["_passive_python"] = retained_proofs + selected_proofs
    info["_analysis_dependency_truncated"] = False
    info["_value_flow"] = local_flow
    info["dependency_bindings"] = graph.cross_bindings
    edges = list({e["edge_id"]: e for e in edges}.values())
    return (nodes, edges, info, dict(changed_files=len(changed), selected_files=len(selected_present),
                                    parsed_python_files=len(selected_present),
                                    reused_python_files=len(python) - len(selected_present),
                                    reused_sites=len(reused_sites), reused_edges=reused_edge_count,
                                    selected_keys=sorted(selected_present),
                                    context_source_files=len(source_context or {}),
                                    context_source_bytes=sum(len(s.encode("utf-8")) for s in (source_context or {}).values()))), (
                                        "general-passive-component" if general else
                                        "certified-simple-python-component")
