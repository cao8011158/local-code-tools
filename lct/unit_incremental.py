"""Owner-level update of the captured Python graph.

This path never admits a source by a syntax whitelist.  It uses immutable old
evidence, changed source hashes and directional owner subscriptions.  Missing
or incompatible evidence returns a reason so the ordinary full build runs.
"""

import ast
import copy
import json
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from types import SimpleNamespace

from . import analysis_inputs, dependency_origins, passive_python, unit_evidence
from .common import canonical, digest
from .evidence_reuse import EvidenceReuseRejected, RebindContext
from .extract import definition_version, extract, module_name
from . import extract as extraction
from .graph import Graph
from .python_analysis import RequiredAnalysisContext
from .python_analysis import Atom, Result
from .simple_python import certify
from .value_flow import evidence as value_flow_evidence


def _signature(tree):
    """Top-level execution of a scope, excluding nested definition bodies."""
    tree = copy.deepcopy(tree)
    def discard_nested(obj):
        for child in ast.iter_child_nodes(obj):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                  ast.Lambda)):
                child.body = [ast.Pass()] if not isinstance(child, ast.Lambda) else ast.Constant(None)
            else:
                discard_nested(child)
    discard_nested(tree)
    return ast.dump(tree, include_attributes=False)


def _owner_changed(old, new, previous, current):
    if old is None or new is None or previous is None or current is None:
        return True
    identity_fields = (("kind", "parent") if old["kind"] == "module" else
                       ("kind", "parent", "definition_line", "column", "end", "end_column"))
    if any(old.get(k) != new.get(k) for k in identity_fields):
        return True
    if old["kind"] == "module":
        return _signature(previous) != _signature(current)
    if old["kind"] == "class":
        return _signature(previous) != _signature(current)
    return (old["fingerprint"] != new["fingerprint"] or
            ast.dump(previous, include_attributes=True) != ast.dump(current, include_attributes=True))


def _unproved_open_receiver_site(site):
    """An opaque instance receiver can consume unrecorded writer inputs.

    A targetless site with this actual coverage gap has no finite producer
    range that certifies its explanation or analysis-input observations.
    Other UNKNOWN sites and concrete receiver candidates remain eligible.
    """
    coverage = site.get("resolution_decision", {}).get("write_source_coverage", {})
    return ("open-receiver-input" in site.get("unresolved_reasons", ()) and
            not site.get("targets") and not site.get("boundaries") and
            isinstance(coverage, dict) and
            coverage.get("rule") == "instance-field-coverage" and
            coverage.get("complete") is not True)


def _candidate_header_changed(previous, current):
    """A class base or decorator can change unrelated receiver candidate traces."""
    if type(previous) is not type(current):
        return True
    fields = ("bases", "keywords", "decorator_list") if isinstance(
        current, ast.ClassDef) else ("decorator_list",)
    return any(ast.dump(ast.Tuple(elts=getattr(previous, name, []), ctx=ast.Load()),
                        include_attributes=False) !=
               ast.dump(ast.Tuple(elts=getattr(current, name, []), ctx=ast.Load()),
                        include_attributes=False) for name in fields)


def _unbounded_changed_effect(tree):
    """Find changed effects whose receiver/value range is not certified here."""
    uncertain = False
    module = isinstance(tree, ast.Module)
    def visit(obj):
        nonlocal uncertain
        for child in ast.iter_child_nodes(obj):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Subscript) and isinstance(child.ctx, (ast.Store, ast.Del)):
                if isinstance(child.slice, ast.Constant):
                    if dependency_origins.key_identity(child.slice.value) is None:
                        uncertain = True
                else:
                    uncertain = True
            elif isinstance(child, ast.Dict) and module:
                for key_expr in child.keys:
                    if (key_expr is None or not isinstance(key_expr, ast.Constant) or
                            dependency_origins.key_identity(key_expr.value) is None):
                        uncertain = True
            elif (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                  and child.func.id in {"exec", "eval", "setattr", "delattr", "globals", "locals"}):
                # An exact attribute spelling does not establish its receiver.
                uncertain = True
            elif (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                  and child.func.attr in {"update", "clear", "pop", "popitem", "setdefault",
                                          "__setitem__", "__delitem__", "append", "extend",
                                          "insert", "remove", "add", "discard"}):
                # EffectCatalog may recognize a concrete origin during analysis,
                # but an old missing writer has no reverse link. Until the
                # origin/range subscription is persisted, recompute the capture.
                uncertain = True
            visit(child)
    visit(tree)
    return uncertain


def _changed_calls_have_unbound_effect(old_tree, new_tree, old_sites, owner):
    """A newly introduced opaque call may write state absent from old indexes."""
    def calls(tree):
        found = {}
        if tree is None:
            return found
        def visit(obj):
            for child in ast.iter_child_nodes(obj):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Call):
                    found[child.func.lineno, child.func.col_offset] = ast.dump(
                        child, include_attributes=False)
                visit(child)
        visit(tree)
        return found
    before, after = calls(old_tree), calls(new_tree)
    prior = {(site["line"], site["column"]): site for site in old_sites
             if site["execution_owner"] == owner and site["kind"] == "call"}
    for position, value in after.items():
        if before.get(position) == value:
            continue
        site = prior.get(position)
        if site is None or not site["targets"]:
            return True
    return False


def _project_observations(ledger, nodes):
    """Recreate legacy module summaries from exact per-owner observations."""
    byid = {n["node_id"]: n for n in nodes}
    modules = {ident: n for ident, n in byid.items() if n["kind"] == "module"}
    reads, watches, events = ledger
    if any(owner not in byid or consumer not in modules or producer not in modules
           for owner, consumer, producer, _ in reads):
        return None
    if any(owner not in byid or consumer not in modules
           for owner, consumer, _, _ in watches):
        return None
    inputs = analysis_inputs.AnalysisInputs(modules)
    for owner, consumer, component, purpose in sorted(events):
        if (owner not in byid or consumer not in modules or
                any(member not in modules for member in component)):
            return None
        inputs.observe(consumer, frozenset(component) if component else None, purpose)
    payload = inputs.export()
    if payload["truncated"]:
        return None
    return (sorted({(consumer, producer, kind)
                    for _, consumer, producer, kind in reads}),
            sorted({(consumer, kind, universe)
                    for _, consumer, kind, universe in watches}), payload)


def _prospective_changed_writer_origins(owner, tree, trees, nodes, graph):
    """Resolve only explicit slot-write receivers with captured AST bindings.

    An unresolved receiver is not a claim that no old reader is affected.
    """
    origins = set()
    def active_write(obj):
        for child in ast.iter_child_nodes(obj):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.Subscript, ast.Attribute)) and isinstance(
                    child.ctx, (ast.Store, ast.Del)):
                return True
            if active_write(child):
                return True
        return False
    if not active_write(tree):
        return origins
    module = nodes[owner]["module"]
    ambiguous = object()

    def bindings(scope, name, before):
        """One unconditional direct binder, with no shadow or hidden write."""
        definition = trees[scope]
        args = getattr(definition, "args", None)
        if args is not None and name in {p.arg for p in (
                args.posonlyargs + args.args + args.kwonlyargs +
                ([args.vararg] if args.vararg else []) +
                ([args.kwarg] if args.kwarg else []))}:
            return ambiguous
        matches = []
        for statement in definition.body:
            if isinstance(statement, (ast.Global, ast.Nonlocal)) and name in statement.names:
                return ambiguous
            if isinstance(statement, ast.ImportFrom) and any(a.name == "*" for a in statement.names):
                return ambiguous
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and (
                    isinstance(statement.targets[0], ast.Name) and
                    statement.targets[0].id == name):
                matches.append(("assign", statement.value))
                continue
            if isinstance(statement, ast.ImportFrom):
                for alias in statement.names:
                    if (alias.asname or alias.name) == name:
                        matches.append(("from", statement, alias))
                continue
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if (alias.asname or alias.name.split(".")[0]) == name:
                        matches.append(("import", alias))
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef)) and statement.name == name:
                return ambiguous
            # A conditional, loop, augmented, delete, destructuring, or
            # assignment-expression binder cannot be an exact receiver proof.
            def shadows(obj):
                if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef, ast.Lambda)):
                    return False
                return (isinstance(obj, ast.Name) and obj.id == name and
                        isinstance(obj.ctx, (ast.Store, ast.Del))) or any(
                            shadows(child) for child in ast.iter_child_nodes(obj))
            if shadows(statement):
                return ambiguous
        if len(matches) != 1:
            return ambiguous if matches else None
        match = matches[0]
        statement = match[1] if match[0] == "from" else next(
            (s for s in definition.body if
             isinstance(s, (ast.Assign, ast.Import)) and
             (match[0] == "assign" and getattr(s, "value", None) is match[1] or
              match[0] == "import" and match[1] in getattr(s, "names", ()))), None)
        if statement is None or (statement.lineno, statement.col_offset) >= before:
            return ambiguous
        return match

    def binding(scope, name, before, visited=None):
        visited = set() if visited is None else visited
        if (scope, name) in visited:
            return None
        visited.add((scope, name))
        found = bindings(scope, name, before)
        if found is ambiguous:
            return None
        if found is None:
            return binding(module, name, (10**9, 10**9), visited) if scope != module else None
        if found[0] == "assign":
            value = found[1]
            if isinstance(value, (ast.Dict, ast.List, ast.Tuple)):
                return {f"{scope}:{value.lineno}:{value.col_offset}"}
            if isinstance(value, ast.Name):
                return binding(scope, value.id, (value.lineno, value.col_offset), visited)
            return None
        if found[0] == "from":
            statement, alias = found[1:]
            if statement.level:
                return None
            candidates = {candidate for candidate in graph.imported(
                nodes[scope]["repository"], statement.module or "")
                if candidate in trees and nodes[candidate]["kind"] == "module"}
            return binding(next(iter(candidates)), alias.name, (10**9, 10**9), visited) if len(candidates) == 1 else None
        return None

    def receiver(expr):
        if isinstance(expr, ast.Name):
            return binding(owner, expr.id, (expr.lineno, expr.col_offset))
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            alias = expr.value.id
            found = bindings(owner, alias, (expr.lineno, expr.col_offset))
            if found is None and owner != module:
                found = bindings(module, alias, (10**9, 10**9))
            if found is not None and found is not ambiguous and found[0] == "import":
                candidates = graph.imported(nodes[owner]["repository"], found[1].name)
                candidates = {candidate for candidate in candidates
                              if candidate in trees and nodes[candidate]["kind"] == "module"}
                return binding(next(iter(candidates)), expr.attr,
                               (10**9, 10**9)) if len(candidates) == 1 else None
        return None

    def visit(obj):
        for child in ast.iter_child_nodes(obj):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Subscript) and isinstance(child.ctx, (ast.Store, ast.Del)):
                found = receiver(child.value)
                if found is None:
                    return False
                origins.update(found)
            elif isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del)):
                return False  # no exact receiver identity subscription yet
            if visit(child) is False:
                return False
        return True
    return origins if visit(tree) else None


def prepare(folder, prior, files, repos, *, dependencies, graph_sites, attempts=None):
    """Return (candidate, mode) or (None, reason) for a compatible old capture."""
    if (prior.get("unit_ast_cache_schema") != unit_evidence.SCHEMA or
            prior.get("unit_observation_schema") != 1 or
            prior.get("origin_dependency_schema") != dependency_origins.SCHEMA or
            prior.get("origin_dependency_coverage") != dependency_origins.COVERAGE or
            prior.get("origin_dependency_truncated") or
            prior.get("analysis_dependency_truncated") or prior.get("analysis_input_truncated") or
            prior["graph"].get("analysis_limited")):
        return None, "previous-owner-evidence-unavailable"
    if (prior.get("value_flow_node_count", 0) or prior.get("value_flow_edge_count", 0)) and (
            prior.get("value_flow_schema") != 1 or
            prior.get("value_flow_coverage") != "certified-dictionary-v1"):
        return None, "previous-value-flow-evidence-unavailable"
    python = {(f["repository"], f["path"]): f for f in files if f["path"].endswith(".py")}
    with closing(sqlite3.connect((folder / "catalog.sqlite").as_uri() +
                                 "?mode=ro&immutable=1", uri=True)) as catalog, closing(
            sqlite3.connect((folder / graph_sites).as_uri() +
                            "?mode=ro&immutable=1", uri=True)) as evidence:
        old_files = {(r, p): (sha, source) for r, p, sha, source in catalog.execute(
            "select repository,path,sha256,text from files")}
        old_python = {k: item for k, item in old_files.items() if k[1].endswith(".py")}
        if any(k not in python or k not in old_python for k in python.keys() | old_python.keys()):
            return None, "python-membership-changed"
        if {k: v[0] for k, v in old_files.items() if k not in old_python} != {
                (f["repository"], f["path"]): f["sha256"] for f in files
                if not f["path"].endswith(".py")}:
            return None, "document-or-other-input-changed"
        changed = {k for k, f in python.items() if old_python[k][0] != f["sha256"]}
        if not changed:
            return None, "no-python-source-change"
        if any(k[1] == "__init__.py" or k[1].endswith("/__init__.py") for k in changed):
            return None, "package-initializer-changed"
        old_nodes = {ident: json.loads(raw) for ident, raw in catalog.execute(
            "select node_id,data from nodes")}
        old_trees = unit_evidence.load(evidence, old_nodes,
                                       {k: v[1] for k, v in old_python.items()})
        order = [ident for (ident,) in evidence.execute(
            "select node_id from node_order order by ordinal")]
        if set(order) != set(old_nodes) or len(order) != len(old_nodes):
            return None, "previous-node-order-invalid"
        old_sites = [json.loads(raw) for (raw,) in evidence.execute(
            "select data from sites order by ordinal")]
        old_open_receiver_owners = {site["execution_owner"] for site in old_sites
                                    if _unproved_open_receiver_site(site)}
        old_edges = [json.loads(raw) for (raw,) in catalog.execute("select data from edges")]
        observations = [json.loads(raw) for (raw,) in evidence.execute(
            "select data from query_observations order by key")]
        imports = [json.loads(raw) for (raw,) in evidence.execute(
            "select data from import_dependencies order by ordinal")]
        requests = [json.loads(raw) for (raw,) in evidence.execute(
            "select data from import_requests order by ordinal")]
        old_reads = list(evidence.execute(
            "select consumer_module,producer_module,kind from analysis_reads"))
        old_watches = list(evidence.execute(
            "select consumer_module,kind,universe from analysis_watches"))
        old_inputs = analysis_inputs.read(evidence, schema=analysis_inputs.SCHEMA)
        old_inputs["truncated"] = False
        old_value_nodes = [json.loads(raw) for (raw,) in evidence.execute(
            "select data from value_nodes")]
        if (prior.get("value_flow_coverage") != "certified-dictionary-v1" and
                (old_value_nodes or evidence.execute(
                    "select 1 from value_edges limit 1").fetchone() or evidence.execute(
                    "select 1 from value_reads limit 1").fetchone())):
            return None, "previous-partial-value-evidence-unavailable"
        old_origin = tuple([json.loads(raw) for (raw,) in evidence.execute(
            "select data from " + table)] for table in
            ("unit_source_supports", "unit_container_subscriptions", "unit_container_writes"))
        old_ledger = unit_evidence.load_owner_observations(evidence)
        if _project_observations(old_ledger, list(old_nodes.values())) != (
                sorted(old_reads), sorted(old_watches), old_inputs):
            return None, "previous-owner-observation-ledger-incomplete"
        # Cache and dependency indexes are covered by FileDependencies' artifact
        # hash validation before this function is called.
        snapshots = {repo: digest(canonical(sorted((f["path"], digest(f["text"]))
                                                  for f in files if f["repository"] == repo)))
                     for repo in {f["repository"] for f in files}}
        fresh_trees = {}
        fresh_nodes = defaultdict(list)
        for key in sorted(changed):
            f = dict(python[key], snapshot_id=snapshots[key[0]])
            ns, trees = extraction.python_nodes(f)
            if attempts is not None:
                attempts["python_files_parsed"] += 1
            fresh_nodes[key].extend(ns)
            fresh_trees.update(trees)
        new_trees = {ident: tree for ident, tree in old_trees.items()
                     if (old_nodes[ident]["repository"], old_nodes[ident]["path"]) not in changed}
        new_trees.update(fresh_trees)
        document_nodes, _ = extract([f for f in files if not f["path"].endswith(".py")])
        document_nodes = [n for n in document_nodes if n["kind"] != "repository"]
        nodes = [dict(node_id=f"{repo}::repository", repository=repo, path="",
                      kind="repository", qualname=repo, parent=None, start=0, end=0,
                      signature="", docstring="", brief="", fingerprint=digest(repo),
                      is_test=False) for repo in sorted(snapshots)]
        by_file = defaultdict(list)
        for ident in order:
            n = old_nodes[ident]
            if n["path"].endswith(".py") and (n["repository"], n["path"]) not in changed:
                by_file[n["repository"], n["path"]].append(n)
        for f in files:
            key = f["repository"], f["path"]
            if key in python:
                if key in changed:
                    nodes.extend(fresh_nodes[key])
                else:
                    for old in by_file[key]:
                        n = dict(old)
                        if (n["source_sha256"] != digest(f["text"]) or
                                n["file_fingerprint"] != f["sha256"]):
                            return None, "unchanged-source-proof-failed"
                        n["snapshot_id"] = snapshots[key[0]]
                        n["version_id"] = definition_version(n)
                        nodes.append(n)
            else:
                nodes.extend(n for n in document_nodes if (n["repository"], n["path"]) == key)
        byid = {n["node_id"]: n for n in nodes}
        if len(nodes) != len(byid) or set(new_trees) != {
                n["node_id"] for n in nodes if n["kind"] in {"module", "class", "function"}}:
            return None, "new-owner-catalog-unavailable"
        graph = Graph(nodes, new_trees, repos)
        if graph.cross_bindings != prior["graph"].get("dependency_bindings"):
            return None, "dependency-bindings-changed"
        changed_owners = {ident for ident in set(old_trees) | set(new_trees)
                          if ident not in old_trees or ident not in new_trees or
                          (ident in old_nodes and (old_nodes[ident]["repository"],
                            old_nodes[ident]["path"]) in changed)}
        # A changed file is parsed in full. Its execution owners are a safe
        # initial seed; only downstream consumers are selected by provenance.
        selected = {ident for ident in new_trees if (byid[ident]["repository"],
                    byid[ident]["path"]) in changed}
        for ident in changed_owners:
            if (ident in old_trees and ident in new_trees and
                    isinstance(new_trees[ident], (ast.ClassDef, ast.FunctionDef,
                                                 ast.AsyncFunctionDef)) and
                    _candidate_header_changed(old_trees[ident], new_trees[ident])):
                return None, "changed-definition-header-candidate-universe"
            selected.update(consumer for consumer, _ in dependencies.unit_readers(ident)
                            if consumer in new_trees)
            if ident in old_trees and ident in new_trees:
                for tree in (old_trees[ident], new_trees[ident]):
                    if _unbounded_changed_effect(tree):
                        return None, "unbounded-changed-writer-input"
                if _changed_calls_have_unbound_effect(old_trees[ident], new_trees[ident],
                                                      old_sites, ident):
                    return None, "changed-opaque-call-effect-unavailable"
            else:
                # New/deleted definitions can satisfy failed candidates and
                # otherwise have no prior producer site to reverse.
                return None, "python-owner-membership-changed"
        # A new writer has no old support edge. Resolve its receiver against
        # captured literal/import bindings and ask the old origin subscriber
        # index; an unsupported receiver deliberately falls back to full.
        for ident in selected.copy():
            old_tree, new_tree = old_trees.get(ident), new_trees.get(ident)
            if old_tree is None or new_tree is None or _signature(old_tree) == _signature(new_tree):
                continue
            origins = _prospective_changed_writer_origins(ident, new_tree, new_trees,
                                                           byid, graph)
            if origins is None:
                return None, "changed-writer-origin-unresolved"
            for origin in origins:
                selected.update(row["consumer_owner"] for row in
                                dependencies.unit_container_readers(origin)
                                if row["consumer_owner"] in new_trees)
        # The old owner ledger records concrete cross-module reads. This also
        # covers member/return/effect inputs not materialized as CALLS.
        old_module_by_file = {(n["repository"], n["path"]): ident
                              for ident, n in old_nodes.items() if n["kind"] == "module"}
        for key in changed:
            module = old_module_by_file.get(key)
            if module is not None:
                selected.update(owner for (owner,) in evidence.execute(
                    "select distinct owner from unit_analysis_reads where producer=?", (module,))
                    if owner in new_trees)
        for ident in changed_owners:
            n = byid.get(ident, old_nodes.get(ident))
            if (n and n["kind"] == "module" and
                    _owner_changed(old_nodes.get(ident), byid.get(ident),
                                   old_trees.get(ident), new_trees.get(ident))):
                key = n["repository"], n["path"]
                affected = (dependencies.importers(n["repository"], n["qualname"])
                            | dependencies.analysis_readers(*key)
                            | dependencies.input_scope_readers(*key))
                selected.update(i for i in new_trees if (byid[i]["repository"],
                                                      byid[i]["path"]) in affected)
        selected.intersection_update(new_trees)
        if not selected:
            return None, "no-affected-owners"
        def expand_dependencies(current):
            pending = deque(current)
            while pending:
                producer = pending.popleft()
                for consumer, _ in dependencies.unit_readers(producer):
                    if consumer in new_trees and consumer not in current:
                        current.add(consumer)
                        pending.append(consumer)
            return current
        selected = expand_dependencies(selected)
        context = {n["node_id"]: python[n["repository"], n["path"]]["text"]
                   for n in nodes if n["kind"] == "module" and n["path"].endswith(".py")}
        # Iterate only when a newly produced call target or an affected owner's
        # output change exposes another actual owner dependency.
        total_queries = total_associations = total_reused_queries = 0
        iterations = 0
        shared_analyzer = None
        changed_scope_owners = None
        previous_work = (0, 0, 0)
        try:
            for _ in range(len(new_trees) + 1):
                if selected & old_open_receiver_owners:
                    return None, "open-receiver-source-coverage-unavailable"
                try:
                    fresh_edges, fresh_info = graph.build(
                        source_context=context, selected_owners=selected,
                        candidate_site_evidence=old_sites, analyzer=shared_analyzer,
                        retain_analyzer=True)
                    shared_analyzer = fresh_info.pop("_analyzer")
                except RequiredAnalysisContext:
                    return None, "required-analysis-context-unavailable"
                if fresh_info["analysis_limited"]:
                    return None, "local-association-budget-limited"
                iterations += 1
                current_work = (fresh_info["jedi_queries_executed"],
                                fresh_info["association_evaluations"],
                                fresh_info["jedi_queries_reused"])
                delta = tuple(current - previous for current, previous in
                              zip(current_work, previous_work))
                previous_work = current_work
                total_queries += delta[0]
                total_associations += delta[1]
                total_reused_queries += delta[2]
                if attempts is not None:
                    attempts["owner_analysis_iterations"] = attempts.get("owner_analysis_iterations", 0) + 1
                    attempts["owner_jedi_queries_executed"] = (
                        attempts.get("owner_jedi_queries_executed", 0) + delta[0])
                    attempts["owner_association_evaluations"] = (
                        attempts.get("owner_association_evaluations", 0) + delta[1])
                if any(_unproved_open_receiver_site(site) for site in fresh_info["sites"]):
                    return None, "open-receiver-source-coverage-unavailable"
                expanded = set(selected)
                # Component policy is computed from the entire new capture.
                # A retained owner's old query scope is invalid when that
                # policy changes, even if no CALLS target changed. Reobserve
                # its actual inputs rather than relabeling the old scope.
                if changed_scope_owners is None:
                    components = shared_analyzer.candidate_components or {}
                    current_members = {consumer: tuple(sorted(component))
                                       for consumer, component in components.items()}
                    changed_scope_owners = {
                        owner for owner, consumer, members, _ in old_ledger[2]
                        if owner in new_trees and
                        members != current_members.get(consumer, ())}
                expanded.update(changed_scope_owners)
                new_calls = {e["target"] for e in fresh_edges if e["kind"] == "CALLS"
                             and e["source"] in selected and e["target"] in new_trees and
                             byid[e["target"]]["kind"] == "function" and
                             unit_evidence.has_parameters(new_trees[e["target"]])}
                expanded.update(new_calls)
                for support in fresh_info.get("_unit_supports", ()):
                    if support["producer_owner"] in selected and support["consumer_owner"] in new_trees:
                        expanded.add(support["consumer_owner"])
                expanded = expand_dependencies(expanded)
                if expanded == selected:
                    break
                selected = expanded
            else:
                return None, "owner-dependency-convergence-unavailable"
        finally:
            if shared_analyzer is not None:
                shared_analyzer.close()
        if prior["graph"].get("association_bound", 20001) + total_associations > 20000:
            return None, "combined-association-budget-uncertified"
        rebinder = RebindContext(old_nodes=old_nodes, new_nodes=byid,
                                old_trees=old_trees, new_trees=new_trees,
                                selected_paths=set())
        try:
            site_ids, retained_sites = {}, []
            for site in old_sites:
                ident = site["execution_owner"]
                if ident in selected:
                    continue
                updated = rebinder.rebind(site, owner_id=ident)
                n = byid[ident]
                updated["site_id"] = digest(canonical([
                    n["repository"], n["path"], n["snapshot_id"], site["line"],
                    site["column"], site["end_line"], site["end_column"], site["kind"]]))
                site_ids[site["site_id"]] = updated["site_id"]
                retained_sites.append(updated)
            def rebind_origin_site(site, owner, location, role):
                if site in site_ids:
                    return site_ids[site]
                n = byid[owner]
                return digest(canonical([n["repository"], n["path"], n["snapshot_id"],
                                         location["line"], location["column"],
                                         location["end_line"], location["end_column"], role]))
            edges, reused_edge_count = [], 0
            for edge in old_edges:
                if edge["kind"] == "CONTAINS" or edge["source"] in selected:
                    continue
                if edge["target"] in changed_owners and edge["source"] in old_trees:
                    return None, "unselected-edge-depends-on-changed-definition"
                updated = dict(edge)
                updated.pop("edge_id")
                if "site_id" in updated:
                    updated["site_id"] = site_ids[edge["site_id"]]
                updated["source_version_id"] = byid.get(edge["source"], {}).get("version_id")
                updated["target_version_id"] = byid.get(edge["target"], {}).get("version_id")
                updated["edge_id"] = digest(canonical(updated))
                edges.append(updated)
                reused_edge_count += 1
            retained_edge_ids = {edge["edge_id"] for edge in edges}
            for n in nodes:
                if n["parent"]:
                    graph.add_edge(n["parent"], n["node_id"], "CONTAINS", "resolved",
                                   "AST lexical ownership", n["start"], n.get("column", 0))
            edges.extend(e for e in fresh_edges if e["kind"] != "CONTAINS")
            edges.extend(e for e in graph.edges if e["kind"] == "CONTAINS")
            # LOOKUP_IN is emitted from an unresolved IMPORTS observation,
            # but its source is the shared boundary rather than the importer.
            # Retain it only while at least one current import still supports
            # that exact boundary and lookup identity. Multiple importers can
            # support the same relation independently.
            lookup_supports = {
                (e["target"], canonical(e["lookup"])) for e in edges
                if e["kind"] == "IMPORTS" and e.get("lookup_status") == "unresolved"
                and e.get("lookup") is not None}
            edges = [e for e in edges if e["kind"] != "LOOKUP_IN" or
                     (e["source"], canonical(e["lookup"])) in lookup_supports]
            reused_edge_count = sum(e["kind"] != "CONTAINS" and
                                    e["edge_id"] in retained_edge_ids for e in edges)
            retained_queries = [rebinder.rebind(r, owner_id=r["execution_owner"])
                                for r in observations if r["execution_owner"] not in selected]
            retained_imports = [r for r in imports if r["source_module"] not in selected]
            retained_requests = [r for r in requests if r["source_module"] not in selected]
            retained_origin = []
            for table, records in enumerate(old_origin):
                kept = []
                for record in records:
                    owner = record["consumer_owner"] if table != 2 else record["producer_owner"]
                    if owner in selected or owner not in byid:
                        continue
                    row = copy.deepcopy(record)
                    if table == 0:
                        if row["producer_owner"] in selected or row["producer_owner"] not in byid:
                            return None, "unselected-source-depends-on-selected-producer"
                        role = "write" if row["kind"] == "container-writer" else (
                            "call" if row["kind"] == "actual-parameter" else "source")
                        row["producer_site"] = rebind_origin_site(
                            row["producer_site"], row["producer_owner"],
                            row["producer_location"], role)
                        row["consumer_site"] = rebind_origin_site(
                            row["consumer_site"], owner, row["consumer_location"], "read")
                        if "call_site" in row["detail"]:
                            row["detail"]["call_site"] = row["consumer_site"]
                        argument = row["detail"].get("argument_source")
                        if argument is not None and "call_site" in argument:
                            argument["call_site"] = row["producer_site"]
                        if "read_site" in row["detail"]:
                            row["detail"]["read_site"] = rebind_origin_site(
                                row["detail"]["read_site"], row["detail"]["read_owner"],
                                row["detail"]["read_location"], "container-read")
                    elif table == 1:
                        row["read_site"] = rebind_origin_site(
                            row["read_site"], row["read_owner"], row["read_location"],
                            "container-read")
                        row["consumer_site"] = rebind_origin_site(
                            row["consumer_site"], owner, row["consumer_location"], "read")
                    else:
                        row["producer_site"] = rebind_origin_site(
                            row["producer_site"], owner, row["producer_location"], "write")
                    kept.append(row)
                retained_origin.append(kept)
        except (EvidenceReuseRejected, KeyError, TypeError, ValueError):
            return None, "old-owner-evidence-rebind-uncertified"
        all_sites = retained_sites + fresh_info["sites"]
        all_sites.sort(key=lambda s: (byid[s["execution_owner"]]["repository"],
                                      byid[s["execution_owner"]]["path"], s["line"],
                                      s["column"], s["kind"]))
        fresh_info["sites"] = all_sites
        fresh_info["call_sites"] = len(all_sites)
        fresh_info["_query_observations"] = list({
            canonical(r["key"]): r for r in
            retained_queries + fresh_info["_query_observations"]}.values())
        fresh_info["_import_dependencies"] = retained_imports + fresh_info["_import_dependencies"]
        request_order = {n["node_id"]: pos for pos, n in enumerate(nodes)
                         if n["kind"] == "module"}
        fresh_requests = fresh_info["_import_requests"]
        if {r["source_module"] for r in retained_requests} & {
                r["source_module"] for r in fresh_requests}:
            # Requests do not persist their source site. An interleaving of
            # retained and recomputed owners within one module has no proven
            # ordinal reconstruction; compute it afresh in a full build.
            return None, "mixed-import-request-order-unavailable"
        fresh_info["_import_requests"] = sorted(
            retained_requests + fresh_requests,
            key=lambda r: request_order[r["source_module"]])
        for key, retained in zip(("_unit_supports", "_unit_subscriptions", "_unit_writes"),
                                 retained_origin):
            fresh_info[key] = list({canonical(r): r for r in
                                    retained + fresh_info[key]}.values())
        fresh_ledger = (set(fresh_info.pop("_unit_analysis_reads")),
                        set(fresh_info.pop("_unit_analysis_watches")),
                        set((owner, consumer, tuple(component), purpose) for
                            owner, consumer, component, purpose in
                            fresh_info.pop("_unit_input_events")))
        if any(owner not in selected for collection in fresh_ledger
               for owner, *_ in collection):
            return None, "selected-owner-observation-boundary-unavailable"
        ledger = tuple({record for record in previous if record[0] not in selected
                        and record[0] in byid} | current
                       for previous, current in zip(old_ledger, fresh_ledger))
        projected = _project_observations(ledger, nodes)
        if projected is None:
            return None, "new-owner-observation-ledger-incomplete"
        fresh_info["_analysis_reads"], fresh_info["_analysis_watches"], fresh_info["_analysis_inputs"] = projected
        fresh_info["_unit_analysis_reads"], fresh_info["_unit_analysis_watches"], fresh_info["_unit_input_events"] = (
            sorted(ledger[0]), sorted(ledger[1]), sorted(ledger[2]))
        fresh_info["_analysis_dependency_truncated"] = (
            fresh_info["_analysis_dependency_truncated"] or
            len(fresh_info["_analysis_reads"]) + len(fresh_info["_analysis_watches"]) > 20000)
        if fresh_info["_analysis_dependency_truncated"]:
            return None, "combined-analysis-dependency-budget-uncertified"
        witnesses = fresh_info.pop("_value_read_witnesses")
        old_site_by_id = {s["site_id"]: s for s in old_sites}
        for record in old_value_nodes:
            if record["kind"] != "read" or record["module"] not in byid:
                continue
            site = old_site_by_id.get(record.get("site_id"))
            if site is None or site["execution_owner"] in selected:
                continue
            witnesses.setdefault((site["execution_owner"], record["line"], record["column"]),
                                 Result(frozenset(Atom("callable", target)
                                                  for target in record["targets"])))
        flow = value_flow_evidence(nodes, new_trees, SimpleNamespace(value_reads=witnesses),
                                   all_sites, graph.imported)
        fresh_info["_value_flow"] = flow
        fresh_info["_simple_python_certificate"] = certify(files, new_trees, graph=graph)
        fresh_info["_passive_python"] = [proof for f in files if f["path"].endswith(".py")
                                         if (proof := passive_python.certify(
                                             f, new_trees.get(f"{f['repository']}:{f['path']}:module:"
                                                              f"{module_name(f['path'])}#1"))) is not None]
        if fresh_info["_simple_python_certificate"] is not None and not flow["complete"]:
            return None, "combined-value-flow-witness-incomplete"
        fresh_info["_ast_cache"] = new_trees
        fresh_info["association_bound"] = (prior["graph"]["association_bound"] +
                                            total_associations)
        fresh_info["association_evaluations"] = total_associations
        fresh_info["jedi_queries_executed"] = total_queries
        fresh_info["jedi_queries_reused"] = total_reused_queries
        fresh_info["jedi_queries"] = total_queries + total_reused_queries
        fresh_info["dependency_bindings"] = graph.cross_bindings
        edges = list({e["edge_id"]: e for e in edges}.values())
        metrics = dict(changed_files=len(changed), selected_files=len(changed),
                       parsed_python_files=len(changed), reused_python_files=len(python)-len(changed),
                       selected_owner_count=len(selected), reused_owner_count=len(new_trees)-len(selected),
                       selected_owner_ids=sorted(selected), selected_keys=sorted(changed),
                       owner_analysis_iterations=iterations,
                       owner_jedi_queries_executed=total_queries,
                       owner_association_evaluations=total_associations,
                       reused_sites=len(retained_sites), reused_edges=reused_edge_count,
                       context_source_files=len(context),
                       context_source_bytes=sum(len(s.encode("utf-8")) for s in context.values()))
        return (nodes, edges, fresh_info, metrics), "incremental-owners"
