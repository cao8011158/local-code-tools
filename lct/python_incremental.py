"""Certified local graph preparation for a small, closed Python subset."""

import ast
import json
import sqlite3
from collections import deque
from contextlib import closing

from . import extract as extraction
from . import python_analysis
from . import analysis_inputs
from .common import canonical, digest
from .evidence_reuse import EvidenceReuseRejected, RebindContext
from .extract import definition_version, extract, module_name
from .graph import Graph
from .simple_python import CERTIFICATE, certify


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


def prepare(folder, prior, files, repos, *, dependencies, graph_sites, attempts=None):
    """Return (nodes, edges, graph, metrics) or (None, reason)."""
    if prior.get("simple_python_certificate") != CERTIFICATE:
        return None, "previous-simple-python-certificate-unavailable"
    if (prior.get("value_flow_schema") != 1 or
            prior.get("value_flow_coverage") != "certified-dictionary-v1"):
        return None, "previous-value-flow-evidence-unavailable"
    if prior.get("analysis_dependency_schema") not in (1, 2) or prior.get("analysis_dependency_truncated"):
        return None, "previous-analysis-dependency-evidence-unavailable"
    if (prior.get("analysis_input_schema") != 1 or
            prior.get("analysis_input_coverage") != "captured-query-scopes-partial" or
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
        # The old sidecar certifies all old modules. New/changed modules must fit
        # the subset; parse the selected closure later, never all unchanged ASTs.
        selected = set(changed)
        queue = deque(sorted(changed))
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
        parsed = {}
        while queue:
            key = queue.popleft()
            candidates = dependencies.adjacent(*key)
            # Use the old exact entry subscriptions, including reads of absent
            # keys; old evidence is indispensable after a write is deleted.
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
        # Certify every selected current AST, including all imported targets. An
        # omitted old module must have no active importer or the gate fails.
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
        # Certification requires the full import universe but only selected ASTs.
        # Supply unchanged module trees from old frozen source only if referenced
        # by a selected import, in which case closure should have selected it.
        if certify(selected_files, local_asts, graph=resolver) != CERTIFICATE:
            return None, "selected-python-syntax-unsupported"
        with closing(sqlite3.connect((folder / graph_sites).as_uri() + "?mode=ro&immutable=1", uri=True)) as evidence:
            try:
                certified = {(r, p): sha for r, p, sha in evidence.execute(
                    "select repository,path,sha256 from simple_python_certificates")}
            except sqlite3.Error:
                return None, "old-syntax-certificates-unavailable"
            old_python = {key: item[0] for key, item in old_files.items()
                          if key[1].endswith(".py")}
            if certified != old_python:
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
            old_input_payload = analysis_inputs.read(evidence)
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
    selected_graph_nodes = [n for n in nodes if n["kind"] == "repository"
                            or (n["repository"], n["path"]) in selected_present]
    graph = Graph(selected_graph_nodes, local_asts, repos)
    full_graph = Graph(nodes, {}, repos)
    if graph.cross_bindings != prior["graph"].get("dependency_bindings"):
        return None, "dependency-bindings-changed"
    local_edges, info = graph.build()
    local_flow = info.get("_value_flow")
    if local_flow is None or not local_flow["complete"]:
        return None, "local-value-flow-witness-incomplete"
    if info["analysis_limited"]:
        return None, "local-association-budget-limited"
    if prior_bound + info["association_evaluations"] > 20000:
        return None, "combined-association-budget-uncertified"
    info["association_bound"] = prior_bound + info["association_evaluations"]
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
                          reads=retained_reads + local_flow["reads"], complete=True)
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
    info["_analysis_dependency_truncated"] = False
    info["_value_flow"] = local_flow
    info["dependency_bindings"] = graph.cross_bindings
    edges = list({e["edge_id"]: e for e in edges}.values())
    return (nodes, edges, info, dict(changed_files=len(changed), selected_files=len(selected_present),
                                    parsed_python_files=len(selected_present),
                                    reused_python_files=len(python) - len(selected_present),
                                    reused_sites=len(reused_sites), reused_edges=reused_edge_count,
                                    selected_keys=sorted(selected_present))), "certified-simple-python-component"
