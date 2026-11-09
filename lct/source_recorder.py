"""Source positions and update subscriptions, without callable value evaluation."""

import ast
from collections import defaultdict
from pathlib import Path

from .common import canonical, digest
from .dependency_origins import LIMIT, key_identity


class SourceRecorder:
    def __init__(self, analyzer, selected_owners=None):
        self.a = analyzer
        self.selected = None if selected_owners is None else set(selected_owners)
        self.supports, self.subscriptions, self.writes = {}, {}, {}
        self.reads, self.watches, self.inputs = set(), set(), set()
        self.truncated = False
        self._origin = defaultdict(set)
        self._origin_cache = {}
        self._owner_sites = defaultdict(list)
        self._module_aliases = defaultdict(set)
        self._prepared_owners = set()
        self._goto_locations = {}
        self._sites_by_owner = defaultdict(list)
        for site in analyzer.sites:
            self._sites_by_owner[site["execution_owner"]].append(site)
        self._binding_owners = defaultdict(set)
        self._parameter_nodes = defaultdict(list)
        self._module_by_stable_path = {
            n["repository"] + "/" + n["path"]: ident
            for ident, n in analyzer.nodes.items() if n["kind"] == "module"}
        for module, tree in analyzer.modules.items():
            for obj in ast.walk(tree):
                if isinstance(obj, ast.Name) and isinstance(obj.ctx, (ast.Store, ast.Del)):
                    execution = analyzer.execution_nodes.get(id(obj), (module, None))[0]
                    self._binding_owners[module, obj.lineno, obj.col_offset].add(execution)
                elif isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    prefix = ("async def " if isinstance(obj, ast.AsyncFunctionDef) else
                              "def " if isinstance(obj, ast.FunctionDef) else "class ")
                    execution = analyzer.execution_nodes.get(id(obj), (module, None))[0]
                    self._binding_owners[module, obj.lineno,
                                         obj.col_offset + len(prefix)].add(execution)
                    if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        target = analyzer.owner.get(id(obj), execution)
                        args = obj.args.posonlyargs + obj.args.args + obj.args.kwonlyargs
                        for arg in args + [p for p in (obj.args.vararg, obj.args.kwarg) if p]:
                            self._binding_owners[module, arg.lineno, arg.col_offset].add(target)
                            self._parameter_nodes[module, arg.lineno, arg.col_offset].append(
                                (target, arg))
                elif isinstance(obj, ast.Lambda):
                    target = analyzer.owner.get(id(obj))
                    if target is not None:
                        args = obj.args.posonlyargs + obj.args.args + obj.args.kwonlyargs
                        for arg in args + [p for p in (obj.args.vararg, obj.args.kwarg) if p]:
                            self._binding_owners[module, arg.lineno, arg.col_offset].add(target)
                            self._parameter_nodes[module, arg.lineno, arg.col_offset].append(
                                (target, arg))
        self.goto_entries = self.goto_executed = self.goto_cache_hits = 0
        self.owner_site_visits = 0
        self.indexed_origin_entries = 0

    def site(self, owner, expr, role):
        node = self.a.nodes[self.a.module_for[owner]]
        return digest(canonical([node["repository"], node["path"], node["snapshot_id"],
                                 getattr(expr, "lineno", 0), getattr(expr, "col_offset", 0),
                                 getattr(expr, "end_lineno", 0), getattr(expr, "end_col_offset", 0), role]))

    def location(self, owner, expr):
        node = self.a.nodes[owner]
        expression = (expr.name if isinstance(expr, (ast.FunctionDef,
                        ast.AsyncFunctionDef, ast.ClassDef)) else ast.unparse(expr)[:240])
        return dict(repository=node["repository"], path=node["path"],
                    line=getattr(expr, "lineno", 0), column=getattr(expr, "col_offset", 0),
                    end_line=getattr(expr, "end_lineno", 0),
                    end_column=getattr(expr, "end_col_offset", 0),
                    expression=expression)

    def record(self, collection, row):
        key = canonical(row)
        if key in collection:
            return
        if len(self.supports) + len(self.subscriptions) + len(self.writes) >= LIMIT:
            self.truncated = True
            return
        collection[key] = row

    def support(self, producer, source, consumer, use, kind, detail=None, status="candidate",
                consumer_site=None):
        self.record(self.supports, dict(producer_owner=producer,
            producer_site=self.site(producer, source, "source"),
            producer_location=self.location(producer, source),
            consumer_owner=consumer, consumer_site=(consumer_site or self.site(consumer, use, "read")),
            consumer_location=self.location(consumer, use),
            kind=kind, status=status, detail=detail or {}))
        self.reads.add((consumer, self.a.module_for[consumer],
                        self.a.module_for[producer], "parameter-origin"
                        if kind == "actual-parameter" else "return-body"))

    def prepare(self):
        """Collect syntactic allocation sites and aliases, irrespective of call targets."""
        for owner, tree in self.a.trees.items():
            for stmt in (tree.body if isinstance(tree, (ast.Module, ast.ClassDef,
                    ast.FunctionDef, ast.AsyncFunctionDef)) else ()):
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,)
                    value = stmt.value
                    if isinstance(value, (ast.Dict, ast.List, ast.Tuple, ast.Call)):
                        for t in targets:
                            if isinstance(t, ast.Name):
                                self._origin[owner, t.id].add(f"{owner}:{value.lineno}:{value.col_offset}")
                    elif isinstance(value, ast.Name):
                        for t in targets:
                            if isinstance(t, ast.Name):
                                self._owner_sites[owner, t.id].append((owner, value))
                if isinstance(stmt, ast.ImportFrom):
                    name = self.import_module(owner, stmt)
                    if not name:
                        continue
                    candidates = [c for c in self.a.imported(
                        self.a.nodes[owner]["repository"], name)
                        if c in self.a.trees and self.a.nodes[c]["kind"] == "module"]
                    if len(candidates) == 1:
                        for alias in stmt.names:
                            self._owner_sites[owner, alias.asname or alias.name].append(
                                (candidates[0], alias.name))
                if isinstance(stmt, ast.Import):
                    for alias in stmt.names:
                        candidates = [c for c in self.a.imported(
                            self.a.nodes[owner]["repository"], alias.name)
                            if c in self.a.trees and self.a.nodes[c]["kind"] == "module"]
                        if len(candidates) == 1:
                            self._module_aliases[owner, alias.asname or alias.name.split(".")[0]].add(
                                candidates[0])
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in stmt.args.defaults + [d for d in stmt.args.kw_defaults if d]:
                        for obj in ast.walk(default):
                            if isinstance(obj, ast.NamedExpr) and isinstance(obj.target, ast.Name):
                                if isinstance(obj.value, (ast.Dict, ast.List, ast.Tuple, ast.Call)):
                                    value = obj.value
                                    self._origin[owner, obj.target.id].add(
                                        f"{owner}:{value.lineno}:{value.col_offset}")
                                elif isinstance(obj.value, ast.Name):
                                    self._owner_sites[owner, obj.target.id].append(
                                        (owner, obj.value))
        # This is an AST alias adjacency index, not an eager Jedi walk. Only
        # a selected consumer's receiver asks for its source ancestry.
        self.indexed_origin_entries = sum(len(origins) for origins in self._origin.values())
        self.add_owners(self.selected)

    def origins_for(self, key, visiting=None):
        cached = self._origin_cache.get(key)
        if cached is not None:
            return cached, True
        if visiting is None:
            visiting = set()
        if key in visiting:
            # A cycle is a set of source relations, not a value fixpoint.
            # Do not cache an incomplete suffix reached through that cycle.
            return set(), False
        visiting.add(key)
        found = set(self._origin.get(key, ()))
        acyclic = True
        for owner, value in self._owner_sites.get(key, ()):
            producers = ({owner} if isinstance(value, str) else
                         self.source_binding_owners(owner, value))
            for producer in producers:
                dependency = (producer, value if isinstance(value, str) else value.id)
                inherited, complete = self.origins_for(dependency, visiting)
                found.update(inherited)
                acyclic &= complete
        visiting.remove(key)
        if acyclic:
            self._origin_cache[key] = found
            self.indexed_origin_entries += len(found)
        return found, acyclic

    def add_owners(self, selected):
        for owner, tree in self.a.trees.items():
            module = self.a.module_for[owner]
            if (selected is not None and owner not in selected) or owner in self._prepared_owners:
                continue
            self._prepared_owners.add(owner)
            for stmt in (tree.body if isinstance(tree, (ast.Module, ast.ClassDef,
                    ast.FunctionDef, ast.AsyncFunctionDef)) else ()):
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and isinstance(stmt.value, ast.Dict):
                    for target in (stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,)):
                        if isinstance(target, ast.Name):
                            origin = f"{owner}:{stmt.value.lineno}:{stmt.value.col_offset}"
                            for key in stmt.value.keys:
                                self.write(origin, key, owner, stmt, "dictionary-literal")
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in stmt.args.defaults + [d for d in stmt.args.kw_defaults if d]:
                        for expression in ast.walk(default):
                            if isinstance(expression, ast.NamedExpr) and isinstance(
                                    expression.value, ast.Dict):
                                value = expression.value
                                origin = f"{owner}:{value.lineno}:{value.col_offset}"
                                for key in value.keys:
                                    self.write(origin, key, owner, expression,
                                               "definition-default-dictionary")
            def visit(obj):
                if obj is not tree and isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                       ast.ClassDef, ast.Lambda)):
                    return
                if isinstance(obj, ast.Dict):
                    # A dictionary unpack reads an unknown range of the
                    # source's keys. This is a dependency, not a copied
                    # callable value or a target conclusion.
                    for key, value in zip(obj.keys, obj.values):
                        if key is not None:
                            continue
                        origins = self.receiver_origins(owner, value)
                        if not origins:
                            self.watches.add((owner, module, "unresolved-container-origin",
                                              "all-captured-python"))
                        for origin in origins:
                            self.subscribe(origin, None, owner, value, ambiguous=True)
                if isinstance(obj, ast.Subscript):
                    origins = self.receiver_origins(owner, obj.value)
                    if not origins and isinstance(obj.ctx, ast.Load):
                        self.watches.add((owner, module, "unresolved-container-origin",
                                          "all-captured-python"))
                    for origin in origins:
                        if isinstance(obj.ctx, ast.Load):
                            self.subscribe(origin, obj.slice, owner, obj,
                                           ambiguous=len(origins) != 1)
                        elif isinstance(obj.ctx, (ast.Store, ast.Del)):
                            self.write(origin, obj.slice, owner, obj, "subscript-write",
                                       status="candidate" if len(origins) != 1 else "observed")
                if isinstance(obj, ast.Attribute):
                    origins = self.receiver_origins(owner, obj.value)
                    if not origins and isinstance(obj.ctx, ast.Load):
                        self.watches.add((owner, module, "unresolved-container-origin",
                                          "all-captured-python"))
                    for origin in origins:
                        key = ast.Constant(value=obj.attr)
                        if isinstance(obj.ctx, ast.Load):
                            self.subscribe(origin, key, owner, obj,
                                           ambiguous=len(origins) != 1)
                        elif isinstance(obj.ctx, (ast.Store, ast.Del)):
                            self.write(origin, key, owner, obj, "field-write",
                                       status="candidate" if len(origins) != 1 else "observed")
                for child in ast.iter_child_nodes(obj):
                    visit(child)
            visit(tree)
            # Source references are distinct from Jedi's inferred callable
            # targets. A goto location supplies only an invalidation input.
            for site in self._sites_by_owner[owner]:
                self.owner_site_visits += 1
                for ref in [site["_expr"], *(site["_call"].args if site["_call"] else ())]:
                    if isinstance(ref, (ast.Name, ast.Attribute)):
                        self.binding(owner, ref)
            if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in tree.body:
                    if isinstance(stmt, ast.Return) and isinstance(stmt.value, (ast.Name, ast.Attribute)):
                        self.binding(owner, stmt.value)

    def import_module(self, owner, stmt):
        if not stmt.level:
            return stmt.module
        current = self.a.nodes[self.a.module_for[owner]]
        package = current["qualname"].split(".")
        if not current["path"].endswith("/__init__.py"):
            package.pop()
        if stmt.level > len(package):
            return None
        return ".".join([*package[:len(package) - stmt.level + 1],
                         *([stmt.module] if stmt.module else [])])

    def receiver_origins(self, owner, expr):
        module = self.a.module_for[owner]
        if isinstance(expr, ast.Name):
            origins = self.origins_for((owner, expr.id))[0]
            if owner == module:
                return origins
            return origins | self.origins_for((module, expr.id))[0]
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            modules = (self._module_aliases[owner, expr.value.id] |
                       self._module_aliases[module, expr.value.id])
            return set().union(*(self.origins_for((m, expr.attr))[0] for m in modules)) if modules else set()
        return set()

    def binding(self, owner, expr):
        for path, line, col, name in self.goto_locations(owner, expr):
            producer_module = self.a.paths.get(Path(path).resolve()) if path else None
            if (producer_module is None or line is None or line < 1 or
                    line > len(self.a._source_lines[producer_module])):
                continue
            # Only source identity and location are consumed. No Jedi Name is
            # converted to a callable or compared to the inferred target.
            source = ast.Name(id=name, ctx=ast.Load())
            source.lineno = source.end_lineno = line
            source_line = self.a._source_lines[producer_module][line - 1]
            source.col_offset = len(source_line[:col].encode("utf-8"))
            source.end_col_offset = source.col_offset + len(name.encode("utf-8"))
            producers = self._binding_owners.get((producer_module, line, source.col_offset),
                                                  {producer_module})
            for producer in producers:
                self.support(producer, source, owner, expr, "source-binding",
                             dict(binding_location=[producer_module, line, source.col_offset]),
                             "observed" if len(producers) == 1 else "candidate")

    def source_binding_owners(self, owner, expr):
        producers = set()
        for path, line, col, name in self.goto_locations(owner, expr):
            module = self.a.paths.get(Path(path).resolve()) if path else None
            if module is None or line is None or line < 1 or line > len(self.a._source_lines[module]):
                continue
            byte_col = len(self.a._source_lines[module][line - 1][:col].encode("utf-8"))
            producers.update(self._binding_owners.get((module, line, byte_col), {module}))
        return producers

    def goto_locations(self, owner, expr):
        module = self.a.module_for[owner]
        key = module, expr.end_lineno, expr.end_col_offset
        self.goto_entries += 1
        if key not in self._goto_locations:
            line = self.a._source_lines[module][expr.end_lineno - 1]
            col = len(line.encode("utf-8")[:expr.end_col_offset].decode("utf-8"))
            try:
                self.goto_executed += 1
                names = self.a.scripts[module].goto(expr.end_lineno, col)
                self._goto_locations[key] = [(str(n.module_path) if n.module_path else "",
                                               n.line, n.column, n.name) for n in names]
            except Exception:
                self._goto_locations[key] = []
        else:
            self.goto_cache_hits += 1
        return self._goto_locations[key]

    @staticmethod
    def key(expr):
        if expr is None:
            return "range", None
        value = key_identity(expr.value) if isinstance(expr, ast.Constant) else None
        return ("exact", value) if value is not None else ("range", None)

    def write(self, origin, key, owner, expr, kind, status="observed"):
        key_kind, address = self.key(key) if key is not None else ("range", None)
        self.record(self.writes, dict(origin=origin, key_kind=key_kind, key=address,
            producer_owner=owner, producer_site=self.site(owner, expr, "write"),
            producer_location=self.location(owner, expr), kind=kind, status=status))

    def subscribe(self, origin, key, owner, expr, ambiguous=False):
        key_kind, address = self.key(key)
        location = self.location(owner, expr)
        self.record(self.subscriptions, dict(origin=origin, key_kind=key_kind,
            key=address, read_owner=owner, read_site=self.site(owner, expr, "container-read"),
            read_location=location, consumer_owner=owner,
            consumer_site=self.site(owner, expr, "read"), consumer_location=location,
            unknown_reasons=["source-origin-candidate"] if ambiguous else []))
        module = self.a.module_for[owner]
        self.reads.add((owner, module, self.a.module_for[origin.rsplit(":", 2)[0]],
                        "container-effects"))
        self.watches.add((owner, module, "slot-writer-universe", "all-captured-python"))

    def observe_query(self, owner, expr):
        module = self.a.module_for[owner]
        self.inputs.add((owner, module, (), "jedi-query"))
        self.a.analysis_inputs.observe(module, None, "jedi-query")

    def call(self, owner, expr, targets, observations):
        """The already mapped Jedi target identifies the callee for argument provenance."""
        if not isinstance(expr, ast.Call):
            return
        for target in targets:
            # Jedi's bound signature removes self/cls. Use the exposed
            # parameter order/kinds and definition positions, including a
            # constructor's __init__ parameters when the target is its class.
            signatures = [row for row in observations if row.get("target") == target]
            for signature in signatures:
                if signature.get("parameters_error"):
                    module = self.a.module_for[target]
                    self.watches.add((target, module, "unresolved-argument-source",
                                      "all-captured-python"))
                parameters = signature.get("parameters", ())
                positional = [p for p in parameters if p["kind"] in (
                    "POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
                variadic = next((p for p in parameters if p["kind"] == "VAR_POSITIONAL"), None)
                keyword_variadic = next((p for p in parameters if p["kind"] == "VAR_KEYWORD"), None)
                supplied = []
                position, unpacked = 0, False
                for arg in expr.args:
                    if isinstance(arg, ast.Starred):
                        unpacked = True
                        supplied.extend((p["name"], arg.value, True)
                                        for p in positional[position:])
                        if variadic:
                            supplied.append((variadic["name"], arg.value, True))
                    elif unpacked:
                        # A preceding unpack can consume zero or more slots.
                        supplied.extend((p["name"], arg, True)
                                        for p in positional[position:])
                        if variadic:
                            supplied.append((variadic["name"], arg, True))
                    elif position < len(positional):
                        supplied.append((positional[position]["name"], arg, False))
                        position += 1
                    elif variadic:
                        supplied.append((variadic["name"], arg, False))
                parameter_names = {p["name"] for p in parameters}
                for kw in expr.keywords:
                    if kw.arg is None:
                        supplied.extend((p["name"], kw.value, True)
                                        for p in parameters if p["kind"] != "POSITIONAL_ONLY")
                    elif kw.arg in parameter_names:
                        supplied.append((kw.arg, kw.value, False))
                    elif keyword_variadic:
                        supplied.append((keyword_variadic["name"], kw.value, False))
                if ((len(expr.args) > len(positional) and variadic is None) or
                        any(kw.arg and kw.arg not in parameter_names and
                            keyword_variadic is None for kw in expr.keywords)):
                    module = self.a.module_for[target]
                    self.watches.add((target, module, "unresolved-argument-source",
                                      "all-captured-python"))
                for name, source, candidate in supplied:
                    for p in parameters:
                        if p["name"] != name:
                            continue
                        module = self._module_by_stable_path.get(p["module_path"])
                        if module is None or p["line"] is None or p["column"] is None:
                            continue
                        source_line = self.a._source_lines[module][p["line"] - 1]
                        col = len(source_line[:p["column"]].encode("utf-8"))
                        for callee, param in self._parameter_nodes.get(
                                (module, p["line"], col), ()):
                            self.support(owner, source, callee, param, "actual-parameter",
                                         dict(call_site=self.site(owner, expr.func, "call"),
                                              call_location=self.location(owner, expr.func),
                                              parameter=name, source_uncertain=candidate),
                                         status="candidate" if candidate else "observed")
            if not signatures and (expr.args or expr.keywords):
                # A mapped function with absent signature detail cannot prove
                # a parameter's precise source. Leave an owner-level watch.
                module = self.a.module_for[target]
                self.watches.add((target, module, "unresolved-argument-source",
                                  "all-captured-python"))

    def export(self):
        return (list(self.supports.values()), list(self.subscriptions.values()),
                list(self.writes.values()))
