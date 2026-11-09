"""Python relationships from the unified catalog, AST sites and mapped Jedi evidence."""

import ast
import tomllib
from collections import defaultdict
from pathlib import Path

from .common import ToolError, canonical, digest, git
from .python_analysis import CALLABLE_KINDS, Analyzer
from .supplemental_calls import SupplementalCalls


def _receiver_context(ident, nodes, trees):
    """Declaring-class source of a method or a closure's free receiver read."""
    lineage = []
    parent = nodes[ident]["parent"]
    while parent in trees and nodes[parent]["kind"] != "class":
        lineage.append(parent)
        parent = nodes[parent]["parent"]
    if parent not in trees or nodes[parent]["kind"] != "class":
        return None
    method = ident if not lineage else lineage[-1]
    if nodes[method]["parent"] != parent or nodes[method]["kind"] != "function":
        return None
    method_tree = trees[method]
    if not isinstance(method_tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    params = method_tree.args.posonlyargs + method_tree.args.args
    static = any(isinstance(d, ast.Name) and d.id == "staticmethod"
                 for d in method_tree.decorator_list)
    receiver = params[0].arg if params and not static else None

    def body_nodes(tree):
        return [tree.body] if isinstance(tree, ast.Lambda) else tree.body

    def active(tree):
        def walk(obj):
            for child in ast.iter_child_nodes(obj):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
                    yield child
                    if isinstance(child, ast.ClassDef):
                        headers = [*child.decorator_list, *child.bases,
                                   *(kw.value for kw in child.keywords)]
                    else:
                        headers = list(getattr(child, "decorator_list", ()))
                        headers += list(child.args.defaults)
                        headers += [d for d in child.args.kw_defaults if d is not None]
                    for header in headers:
                        yield header
                        yield from walk(header)
                    continue
                yield child
                yield from walk(child)
        for stmt in body_nodes(tree):
            yield stmt
            yield from walk(stmt)

    def shadowed(tree, name):
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return True
        args = tree.args
        parameters = args.posonlyargs + args.args + args.kwonlyargs
        parameters += [a for a in (args.vararg, args.kwarg) if a]
        declarations = {n for obj in active(tree) if isinstance(obj, ast.Global)
                        for n in obj.names}
        if name in declarations:
            return True
        if any(arg.arg == name for arg in parameters):
            return True
        if any(isinstance(obj, ast.Name) and obj.id == name and
               isinstance(obj.ctx, (ast.Store, ast.Del)) for obj in active(tree)):
            return True
        if any(isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               and obj.name == name for obj in active(tree)):
            return True
        if any(isinstance(obj, (ast.Import, ast.ImportFrom)) and any(
                (alias.asname or (alias.name if isinstance(obj, ast.ImportFrom)
                                  else alias.name.split(".")[0])) == name for alias in obj.names)
               for obj in active(tree)):
            return True
        return False

    def aliases(tree, inherited):
        """Follow simple local cell copies without entering nested bodies."""
        names = set(inherited)
        changed = True
        while changed:
            changed = False
            for obj in active(tree):
                if isinstance(obj, ast.Assign) and isinstance(obj.value, ast.Name):
                    targets, source = obj.targets, obj.value.id
                elif isinstance(obj, ast.AnnAssign) and isinstance(obj.value, ast.Name):
                    targets, source = [obj.target], obj.value.id
                else:
                    continue
                if source not in names:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in names:
                        names.add(target.id)
                        changed = True
        return names

    def defaults(tree, inherited):
        """Definition-time receiver values bound to nested parameters."""
        args = tree.args
        positional = args.posonlyargs + args.args
        pairs = list(zip(positional[-len(args.defaults):], args.defaults)) if args.defaults else []
        pairs += [(arg, value) for arg, value in zip(args.kwonlyargs, args.kw_defaults)
                  if value is not None]
        return {arg.arg for arg, value in pairs
                if isinstance(value, ast.Name) and value.id in inherited}

    tree = trees[ident]
    if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return None
    reads = {obj.id for obj in active(tree)
             if isinstance(obj, ast.Name) and isinstance(obj.ctx, ast.Load)}
    for name in (receiver, "__class__", "super"):
        if name is None:
            continue
        if ident == method:
            if name != receiver and shadowed(tree, name):
                continue
            available = aliases(tree, {name})
        else:
            available = aliases(method_tree, {name})
            for ancestor in reversed(lineage[:-1]):
                inherited = available
                available = {value for value in available
                             if not shadowed(trees[ancestor], value)}
                available.update(defaults(trees[ancestor], inherited))
                available = aliases(trees[ancestor], available)
            inherited = available
            available = {value for value in available if not shadowed(tree, value)}
            available.update(defaults(tree, inherited))
            available = aliases(tree, available)
        captured = sorted(reads & available)
        if not captured:
            continue
        return parent, method, captured[0]
    return None


class Graph:
    """Compatibility facade; site completeness is explicit, never fixed-point cardinality."""

    def __init__(self, nodes, asts, repos):
        self.nodes = {n["node_id"]: n for n in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("Node identity collision")
        self.asts = asts
        self.repos = {r["name"]: r for r in repos}
        self.modules = defaultdict(set)
        self.cross_bindings = {}
        self.edges = []
        for n in nodes:
            if n["kind"] == "module":
                self.modules[n["repository"], n["qualname"]].add(n["node_id"])
        for repo in repos:
            p = Path(repo["path"]) / "pyproject.toml"
            if p.exists():
                data = tomllib.loads(p.read_text(encoding="utf-8-sig"))
                sources = data.get("tool", {}).get("uv", {}).get("sources", {})
                for name, value in sources.items():
                    if isinstance(value, dict) and "trpg-rules-engine" in value.get("git", ""):
                        pin = value.get("rev")
                        target = self.repos.get("trpg-rules-engine", {})
                        clean = None
                        if pin == target.get("head") and pin:
                            try:
                                clean = not bool(
                                    git(
                                        target["path"],
                                        "status",
                                        "--porcelain",
                                        "--untracked-files=all",
                                        "--",
                                        "*.py",
                                    )
                                )
                            except (ToolError, KeyError):
                                clean = False
                        record = {
                            "pin": pin,
                            "target_head": target.get("head"),
                            "matched": pin == target.get("head") and clean is True,
                            "worktree_python_clean": clean,
                            "dependency": name,
                        }
                        group = self.cross_bindings.setdefault(repo["name"], {"dependencies": {}})
                        group["dependencies"][name] = record
                        group["matched"] = all(r["matched"] for r in group["dependencies"].values())
                        pins = {r["pin"] for r in group["dependencies"].values()}
                        group["pin"] = next(iter(pins)) if len(pins) == 1 else None
                        group["target_head"] = target.get("head")

    def imported(self, repo, name):
        """Cross-repository targets require the exact dependency revision to match."""
        local = self.modules.get((repo, name), set())
        if local:
            return set(local)
        if name.startswith(("dnd5e_engine", "dnd5e_srd_data")):
            dependency = "dnd5e-engine" if name.startswith("dnd5e_engine") else "dnd5e-srd-data"
            binding = self.cross_bindings.get(repo, {}).get("dependencies", {}).get(dependency, {})
            if binding.get("matched"):
                return set(self.modules.get(("trpg-rules-engine", name), set()))
            if repo != "trpg-rules-engine":
                return {"boundary:dependency-version-unmatched:" + name}
        return {"boundary:external-or-excluded:" + name}

    def named_import_namespace(self, scope, stmt, alias):
        """Identify one captured namespace used by a named import, including reexports."""
        name = self.import_request_module(scope, stmt, alias)
        if not isinstance(stmt, ast.ImportFrom) or alias.name == "*" or not name:
            return None
        caller = self.nodes[scope]
        allowed = self.imported(caller["repository"], name)
        if len(allowed) != 1:
            return None
        module = next(iter(allowed))
        if module not in self.nodes or self.nodes[module]["kind"] != "module":
            return None
        owner = self.nodes[module]
        identity = dict(repository=owner["repository"], module=name, name=alias.name)
        return module, identity

    def import_request_module(self, scope, stmt, alias):
        """Syntactic module search key; it does not certify module ownership."""
        if isinstance(stmt, ast.Import):
            return alias.name
        module_node = scope
        while self.nodes[module_node]["kind"] != "module":
            module_node = self.nodes[module_node]["parent"]
        current = self.nodes[module_node]
        if stmt.level:
            package = current["qualname"].split(".")
            if not current["path"].endswith("/__init__.py"):
                package.pop()
            if stmt.level > len(package):
                return None
            prefix = package[:len(package) - stmt.level + 1]
            name = ".".join([*prefix, *([stmt.module] if stmt.module else [])])
        else:
            name = stmt.module or ""
        return name or None

    def import_lookup(self, scope, stmt, alias, *, namespace=None):
        """Keep a named boundary for a unique namespace or scoped absent module."""
        match = namespace
        if match:
            module, identity = match
        else:
            name = self.import_request_module(scope, stmt, alias)
            if not isinstance(stmt, ast.ImportFrom) or alias.name == "*" or not name:
                return None
            repository = self.nodes[scope]["repository"]
            allowed = self.imported(repository, name)
            # A pinned but unmatched dependency, or two captured modules with the
            # same name, cannot be used as evidence of a unique search namespace.
            if allowed != {"boundary:external-or-excluded:" + name}:
                return None
            identity = dict(repository=repository, module=name, name=alias.name,
                            scope="requester")
            module = None
        if self.modules.get((self.nodes[scope]["repository"], identity["module"] + "." + alias.name)):
            return None
        return module, "boundary:unresolved-import:" + digest(canonical(identity)), identity

    def add_edge(
        self, source, target, kind, status, basis, line=0, column=0, expression="", **extra
    ):
        """Store typed relations; CALLS edges are projections of a particular site."""
        edge = dict(
            source=source,
            target=target,
            kind=kind,
            status=status,
            basis=basis,
            line=line,
            column=column,
            expression=expression,
            **extra,
        )
        edge["source_version_id"] = self.nodes.get(source, {}).get("version_id")
        edge["target_version_id"] = self.nodes.get(target, {}).get("version_id")
        edge["edge_id"] = digest(canonical(edge))
        self.edges.append(edge)

    def build(self, source_context=None, selected_owners=None,
              candidate_site_evidence=None, analyzer=None, retain_analyzer=False,
              prior_source_evidence=None):
        """Analyze captured bytes only; return edges plus the independent site inventory."""
        self.edges = []
        for n in self.nodes.values():
            if n["parent"]:
                self.add_edge(
                    n["parent"],
                    n["node_id"],
                    "CONTAINS",
                    "resolved",
                    "AST lexical ownership",
                    n["start"],
                    n.get("column", 0),
                )
        analyzer = analyzer or Analyzer(
            self.nodes, self.asts, self.repos, self.imported,
            source_context=source_context,
            candidate_site_evidence=candidate_site_evidence,
            selected_owners=selected_owners)
        succeeded = False
        try:
            selected = None if selected_owners is None else frozenset(selected_owners)
            analyzer.recorder.add_owners(selected)
            def chosen(owner):
                return selected is None or owner in selected
            # This relation exists even when a base or receiver is unresolved:
            # changing the declaring class can alter a method's MRO lookup.
            # It is a source dependency, not an invocation edge.
            for ident, tree in self.asts.items():
                if not chosen(ident):
                    continue
                context = _receiver_context(ident, self.nodes, self.asts)
                if context is not None:
                    declaring, method, receiver = context
                    analyzer.recorder.support(
                        declaring, self.asts[declaring], ident, tree,
                        "class-receiver-context",
                        dict(receiver=receiver, via_method=method),
                        status="observed")
            sites = []
            import_dependencies = []
            import_requests = []
            observations = []
            for item in analyzer.sites:
                expr, scope = item["_expr"], item["execution_owner"]
                if not chosen(scope):
                    continue
                signal = (analyzer.query(scope, item["_call"], signature=True)
                          if item["kind"] == "call" else analyzer.query(scope, expr))
                raw_key = ((analyzer.module_for[scope],
                            *analyzer.signature_position(item["_call"]), "signature")
                           if item["kind"] == "call" else
                           (analyzer.module_for[scope], expr.end_lineno,
                            expr.end_col_offset, False))
                raw = analyzer.queries.get(raw_key, (None, []))[1]
                primary = sorted(a.target for a in signal.atoms if a.kind in CALLABLE_KINDS)
                analyzer.recorder.call(scope, item["_call"], primary, raw)
                observations.append((item, signal, raw))
            eligible = [(item, signal, raw) for item, signal, raw in observations
                        if item["kind"] == "call" and not raw and
                        signal.reasons == frozenset({"jedi-no-result"}) and
                        isinstance(item["_expr"], (ast.Name, ast.Subscript))]
            supplementer = (SupplementalCalls(analyzer, prior_source_evidence, selected)
                            if eligible else None)
            supplements = {}
            for item, signal, raw in eligible:
                found, sources = supplementer.container(item)
                if not found:
                    continue
                supplements[item["site_id"]] = (found, sources, "container")
                supplementer.support(item, sources, found)
                target = next(iter(found))
                parameters = (supplementer.definition_parameters(target, sources[0])
                              if item["_call"].args or item["_call"].keywords else [])
                if parameters:
                    analyzer.recorder.call(item["execution_owner"], item["_call"],
                                           found, [dict(target=target, parameters=parameters)])
            for item, signal, raw in eligible:
                if item["site_id"] in supplements:
                    continue
                found, sources = supplementer.callback(item)
                if found:
                    supplements[item["site_id"]] = (found, sources, "callback")
                    supplementer.support(item, sources, found)
            for item, signal, raw_observations in observations:
                expr, scope = item["_expr"], item["execution_owner"]
                targets = sorted({a.target for a in signal.atoms if a.kind in CALLABLE_KINDS})
                supplement = supplements.get(item["site_id"])
                if supplement:
                    targets = sorted(supplement[0])
                boundaries = sorted({a.target for a in signal.atoms if a.kind == "boundary"})
                reasons = sorted(signal.reasons)
                if any(b.startswith("dependency-version-unmatched:") for b in boundaries):
                    reasons.append("dependency-version-unmatched")
                complete = not reasons
                record = {k: v for k, v in item.items() if not k.startswith("_")}
                record.update(
                    targets=targets,
                    unknown_origin=bool(reasons),
                    complete=complete,
                    completeness_basis="jedi-observation-mapped" if complete else None,
                    resolution_kind=("supplemented-source" if supplement else
                                     "mapped-observation" if targets or boundaries else
                                     "unsupported-or-unknown"),
                    target_provider=("jedi-source-supplement" if supplement else
                                     "jedi-get-signatures" if item["kind"] == "call"
                                     else "jedi-infer"),
                    unresolved_reasons=reasons,
                    boundaries=[
                        dict(
                            full_name=b,
                            reason="dependency-version-unmatched"
                            if b.startswith("dependency-version-unmatched:")
                            else "external-or-excluded",
                        )
                        for b in boundaries
                    ],
                    evidence=[
                        dict(tool="ast", role="site and execution phase"),
                        dict(
                            tool="jedi",
                            version="0.20.1",
                            role=("call signature" if item["kind"] == "call"
                                  else "inferred definition"),
                            api=("get_signatures" if item["kind"] == "call" else "infer"),
                            position=(list(analyzer.signature_position(item["_call"]))
                                      if item["kind"] == "call" else
                                      [expr.end_lineno, expr.end_col_offset]),
                            raw=raw_observations,
                        ),
                    ],
                )
                if supplement:
                    record["evidence"].append(dict(tool="source-association",
                        kind=supplement[2], sources=[dict(owner=s[0],
                            location=analyzer.recorder.location(s[0], s[1]))
                            for s in supplement[1]],
                        targets=targets, scope="exact-source-association"))
                sites.append(record)
                for target in targets:
                    if target in analyzer.trees:
                        analyzer.recorder.support(
                            target, analyzer.trees[target], scope, expr, "call-target",
                            dict(call_site=item["site_id"], target_id=target,
                                 unknown_reasons=reasons),
                            "observed" if complete and len(targets) == 1 and not boundaries
                            else "candidate", consumer_site=item["site_id"])
                status = (
                    "resolved" if complete and len(targets) + len(boundaries) == 1 else "possible"
                )
                for target in targets:
                    self.add_edge(
                        scope,
                        target,
                        "CALLS",
                        status,
                        "bounded Jedi-empty source association" if supplement else
                        "mapped AST/Jedi site",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                        target_role="definition",
                        invocation_phase="ordinary-call",
                    )
                for boundary in boundaries:
                    target = "boundary:" + (
                        "dependency-version-unmatched:" + boundary.split(":", 1)[1]
                        if boundary.startswith("dependency-version-unmatched:")
                        else "external-or-excluded:" + boundary
                    )
                    self.add_edge(
                        scope,
                        target,
                        "CALLS",
                        "boundary",
                        "captured source boundary",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                    )
                if not targets and not boundaries:
                    self.add_edge(
                        scope,
                        None,
                        "CALLS",
                        "unresolved",
                        "; ".join(reasons) or "invalid/noncallable target",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                    )
            for ident, tree in self.asts.items():
                if not chosen(self.nodes[ident]["parent"]):
                    continue
                if (
                    not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or len(tree.decorator_list) != 1
                ):
                    continue
                decorator = tree.decorator_list[0]
                decorator_name = decorator.func if isinstance(decorator, ast.Call) else decorator
                observed = analyzer.query(self.nodes[ident]["parent"], decorator_name)
                for atom in observed.atoms:
                    if atom.kind == "boundary" and atom.target in (
                            "contextlib.contextmanager", "contextlib.asynccontextmanager"):
                        self.add_edge("boundary:external-or-excluded:" + atom.target,
                                      ident, "WRAPS", "resolved", "Jedi decorator observation",
                                      tree.lineno, tree.col_offset, wrapper_origin=atom.target)
            for scope, statement, context in analyzer.context_sites:
                if not chosen(scope):
                    continue
                # A context expression is observable even when Jedi does not
                # establish the entered/resumed body. Preserve the boundary.
                self.add_edge(scope, None, "CONTEXT_ENTERS", "unresolved",
                              "context entry target not supplied by Jedi observation",
                              context.lineno, context.col_offset, ast.unparse(context),
                              complete=False, unknown_origin=True,
                              unresolved_reasons=["context-enter-target-unobserved"])
            for scope, expr, phase in analyzer.references:
                if not chosen(scope):
                    continue
                result = analyzer.query(scope, expr)
                for a in result.atoms:
                    if a.kind in CALLABLE_KINDS or a.kind == "module":
                        self.add_edge(
                            scope,
                            a.target,
                            "REFERENCES",
                            "possible" if result.unknown else "resolved",
                            "AST value reference; never implies invocation",
                            expr.lineno,
                            expr.col_offset,
                            ast.unparse(expr),
                            phase=phase,
                        )
            for scope, stmt in analyzer.import_sites:
                if not chosen(scope):
                    continue
                for alias_index, alias in enumerate(stmt.names):
                    result = analyzer.query(scope, alias)
                    namespace = self.named_import_namespace(scope, stmt, alias)
                    source = self.nodes[scope]
                    requested_module = self.import_request_module(scope, stmt, alias)
                    targets = sorted(a.target for a in result.atoms if a.target in self.nodes)
                    import_requests.append(dict(
                        source_module=source["module"],
                        source_owner=scope, source_line=stmt.lineno,
                        source_column=stmt.col_offset, alias_index=alias_index,
                        bound_name=alias.asname or (alias.name if isinstance(stmt, ast.ImportFrom)
                                                    else alias.name.split(".")[0]),
                        source_repository=source["repository"],
                        requested_module=requested_module,
                        requested_name=alias.name if isinstance(stmt, ast.ImportFrom) else None,
                        request_kind="from" if isinstance(stmt, ast.ImportFrom) else "import",
                        lookup_repository=namespace[1]["repository"] if namespace else source["repository"],
                        namespace_module=namespace[0] if namespace else None,
                        status="resolved" if targets else "boundary" if result.atoms else "unresolved",
                        target_ids=targets,
                        target_modules=sorted({self.nodes[target]["module"] for target in targets}),
                    ))
                    if namespace:
                        import_dependencies.append(dict(
                            source_module=source["module"], namespace_module=namespace[0],
                            source_owner=scope, source_line=stmt.lineno,
                            source_column=stmt.col_offset, alias_index=alias_index,
                            requested_name=namespace[1]["name"],
                            target_modules=sorted({self.nodes[target]["module"] for target in targets}),
                            target_ids=targets, resolved=bool(targets),
                        ))
                    for a in result.atoms:
                        external = a.kind in ("boundary", "external-module", "external-value")
                        target = a.target
                        if external:
                            target = "boundary:" + (
                                a.target
                                if a.target.startswith("dependency-version-unmatched:")
                                else "external-or-excluded:" + a.target
                            )
                        self.add_edge(
                            scope,
                            target,
                            "IMPORTS",
                            "boundary" if external else "resolved",
                            "exact captured import definition",
                            stmt.lineno,
                            stmt.col_offset,
                            alias.name,
                        )
                    if not result.atoms:
                        reasons = sorted(result.reasons)
                        lookup = self.import_lookup(scope, stmt, alias, namespace=namespace)
                        target = lookup[1] if lookup else None
                        detail = dict(lookup=lookup[2], lookup_status="unresolved",
                                      unresolved_reasons=reasons, unknown_origin=True,
                                      complete=False) if lookup else {}
                        self.add_edge(
                            scope, target, "IMPORTS", "unresolved",
                            "; ".join(reasons), stmt.lineno, stmt.col_offset,
                            alias.name, **detail,
                        )
                        if lookup and lookup[0] is not None:
                            self.add_edge(
                                target, lookup[0], "LOOKUP_IN", "resolved",
                                "unique captured import lookup namespace; name unresolved",
                                lookup=lookup[2], lookup_status="unresolved",
                            )
            for ident, scope, base in analyzer.inheritance:
                if not chosen(scope):
                    continue
                result = analyzer.query(scope, base)
                for a in result.atoms:
                    if a.kind == "class":
                        self.add_edge(
                            ident,
                            a.target,
                            "INHERITS",
                            "resolved",
                            "explicit AST base",
                            base.lineno,
                            base.col_offset,
                            ast.unparse(base),
                        )
            sites.sort(key=lambda site: (
                self.nodes[site["execution_owner"]]["repository"],
                self.nodes[site["execution_owner"]]["path"],
                site["line"], site["column"], site["kind"], site["site_id"]))
            self.edges = list({e["edge_id"]: e for e in self.edges}.values())
            flow = dict(nodes=[], edges=[], reads=[], complete=False)
            recorder = analyzer.recorder
            info = dict(
                engine="AST catalog + Jedi 0.20.1 observations",
                schema=4,
                sites=sites,
                call_sites=len(sites),
                jedi_queries=len(analyzer.queries),
                jedi_queries_reused=analyzer.reused_queries,
                jedi_queries_executed=analyzer.executed_queries,
                jedi_query_entries=analyzer.query_entries,
                jedi_query_cache_hits=analyzer.query_cache_hits,
                jedi_raw_observation_hits=analyzer.raw_jedi_observation_hits,
                jedi_raw_result_counts=dict(analyzer.raw_query_counts),
                jedi_source_query_entries=recorder.goto_entries,
                jedi_source_query_cache_hits=recorder.goto_cache_hits,
                jedi_source_queries_executed=recorder.goto_executed,
                jedi_total_queries_executed=(analyzer.executed_queries +
                                             recorder.goto_executed +
                                             (supplementer.metadata_queries if supplementer else 0)),
                supplemental_calls=len(supplements),
                supplemental_source_query_entries=(supplementer.source_queries if supplementer else 0),
                supplemental_metadata_queries_executed=(supplementer.metadata_queries if supplementer else 0),
                source_origin_index_entries=recorder.indexed_origin_entries,
                source_owner_site_visits=recorder.owner_site_visits,
                source_subscriptions=len(recorder.subscriptions),
                source_writes=len(recorder.writes),
                candidate_site_queries_prepared=analyzer.site_queries_prepared,
                _query_observations=[],
                _import_dependencies=import_dependencies,
                _import_requests=import_requests,
                _analysis_reads=sorted({(c, p, k) for _, c, p, k in recorder.reads}),
                _analysis_watches=sorted({(c, k, u) for _, c, k, u in recorder.watches}),
                _analysis_inputs=analyzer.analysis_inputs.export(),
                _unit_analysis_reads=sorted(recorder.reads),
                _unit_analysis_watches=sorted(recorder.watches),
                _unit_input_events=sorted(recorder.inputs),
                _unit_supports=list(recorder.supports.values()),
                _unit_subscriptions=list(recorder.subscriptions.values()),
                _unit_writes=list(recorder.writes.values()),
                _unit_dependency_truncated=recorder.truncated,
                _value_flow=flow,
                _value_read_witnesses={},
                _analysis_dependency_truncated=recorder.truncated,
                dependency_bindings=self.cross_bindings,
                closed_world={k: bool(r.get("closed_world", False)) for k, r in self.repos.items()},
                limits="Jedi observation; source evidence limit 20k",
            )
            if retain_analyzer:
                info["_analyzer"] = analyzer
            succeeded = True
            return self.edges, info
        finally:
            if not retain_analyzer or not succeeded:
                analyzer.close()
