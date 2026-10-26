"""Conservative Python points-to analysis over AST; never executes indexed modules.

Lexical bindings, imports, constructors, assignments, annotations, returns, callback
arguments and mapping writes feed a monotone bounded fixed point. Dynamic behavior
is retained as unresolved evidence. This is a source approximation, not a runtime trace.
"""

import ast
import tomllib
from collections import defaultdict
from pathlib import Path

from .common import ToolError, canonical, digest, git


class Graph:
    """Keep scopes, value origins and edges separate from vector-neighbor HNSW data."""

    def __init__(self, nodes, asts, repos):
        self.nodes = {n["node_id"]: n for n in nodes}
        self.asts = asts
        self.repos = {r["name"]: r for r in repos}
        self.bindings = defaultdict(set)
        self.members = defaultdict(set)
        self.attrs = defaultdict(set)
        self.maps = defaultdict(set)
        self.returns = defaultdict(set)
        self.modules = defaultdict(set)
        self.module_for = {}
        self.scopes = {}
        self.bases = defaultdict(set)
        self.imports = []
        self.call_sites = []
        self.assignments = []
        self.return_sites = []
        self.annotations = []
        self.edges = []
        self.cross_bindings = {}
        self.saturated = False
        self.limited = False
        self.value_calls = 0
        self.local_names = defaultdict(set)
        self.memo = {}
        self.forward_refs = {}
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

        for n in nodes:
            ident = n["node_id"]
            if n["parent"]:
                self.add_edge(
                    n["parent"], ident, "CONTAINS", "resolved", "lexical ownership", n["start"]
                )
            if n["kind"] == "module":
                self.modules[n["repository"], n["qualname"]].add(ident)
            if ident in asts and n["kind"] != "module":
                self.bindings[n["parent"], asts[ident].name].add(ident)
                self.members[n["parent"], asts[ident].name].add(ident)
        for ident in asts:
            scope = ident
            while self.nodes[scope]["kind"] != "module":
                scope = self.nodes[scope]["parent"]
            self.module_for[ident] = scope
        for ident, tree in asts.items():
            self.scan_scope(ident, tree)

    def add_edge(self, source, target, kind, status, basis, line=0, column=0, expression=""):
        """A call with multiple known targets emits possible edges, unknown sites remain."""
        e = dict(
            source=source,
            target=target,
            kind=kind,
            status=status,
            basis=basis,
            line=line,
            column=column,
            expression=expression,
        )
        e["edge_id"] = digest(canonical(e))
        self.edges.append(e)

    def scan_scope(self, scope, tree):
        """Collect direct-scope operations; nested functions have their own analysis scope."""
        if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = self.nodes.get(self.nodes[scope]["parent"], {})
            if owner.get("kind") == "class" and tree.args.args:
                self.bindings[scope, tree.args.args[0].arg].add("instance:" + owner["node_id"])
            for param in tree.args.posonlyargs + tree.args.args + tree.args.kwonlyargs:
                self.local_names[scope].add(param.arg)
                if param.annotation:
                    self.annotations.append((scope, ast.Name(id=param.arg), param.annotation))
        if isinstance(tree, ast.ClassDef):
            for base in tree.bases:
                self.annotations.append((scope, None, base))

        def walk(n):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Decorators/defaults are evaluated by the owner, not function body.
                for x in n.decorator_list:
                    walk(x)
                return
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                self.imports.append((scope, n))
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for target in targets:
                    self.assignments.append((scope, target, n.value))
                    for assigned in ast.walk(target):
                        if isinstance(assigned, ast.Name) and isinstance(assigned.ctx, ast.Store):
                            self.local_names[scope].add(assigned.id)
                    if isinstance(n, ast.AnnAssign) and n.annotation:
                        self.annotations.append((scope, target, n.annotation))
            elif isinstance(n, ast.Call):
                self.call_sites.append((scope, n))
            elif isinstance(n, ast.Return) and n.value:
                self.return_sites.append((scope, n.value))
            for child in ast.iter_child_nodes(n):
                walk(child)

        for item in tree.body:
            walk(item)

    def lookup(self, scope, name):
        """Follow lexical scopes; a local binding is not replaced by global same-name guesses."""
        while scope in self.nodes:
            result = self.bindings.get((scope, name), set())
            if result or name in self.local_names.get(scope, set()):
                return set(result)
            scope = self.nodes[scope]["parent"]
        return set()

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

    def attribute(self, values, name, visited=None):
        """Resolve owned/inherited attributes; unknown receivers produce no fake edge."""
        result = set()
        visited = visited or set()
        for value in sorted(values):
            if value.startswith("boundary:"):
                result.add(value + "." + name)
                continue
            cls = value.removeprefix("instance:")
            if cls in visited:
                continue
            visited.add(cls)
            owned = (
                self.members.get((cls, name), set())
                | self.bindings.get((cls, name), set())
                | self.attrs.get((cls, name), set())
            )
            result |= owned or self.attribute(self.bases.get(cls, set()), name, visited)
        return result

    def values(self, scope, expr, depth=0):
        """Memoize repeated AST subexpressions inside one fixed-point stage."""
        key = (scope, id(expr), depth)
        if key in self.memo:
            return self.memo[key]
        result = self._values(scope, expr, depth)
        if len(result) > 64:
            self.limited = True
            result = set(sorted(result)[:64])
        self.memo[key] = result
        return result

    def _values(self, scope, expr, depth=0):
        """Infer source-level callable/instance/map values, with bounded recursion."""
        self.value_calls += 1
        if self.value_calls > 2000000:
            self.limited = True
            return set()
        if expr is None or depth > 6:
            return set()
        if isinstance(expr, ast.Name):
            return self.lookup(scope, expr.id)
        if isinstance(expr, ast.Attribute):
            return self.attribute(self.values(scope, expr.value, depth + 1), expr.attr)
        if isinstance(expr, ast.Call):
            targets = self.values(scope, expr.func, depth + 1)
            result = set()
            for target in sorted(targets):
                if self.nodes.get(target, {}).get("kind") == "class":
                    result.add("instance:" + target)
                result |= self.returns.get(target, set())
            return result
        if isinstance(expr, (ast.IfExp, ast.BoolOp, ast.Tuple, ast.List, ast.Set)):
            parts = (
                [expr.body, expr.orelse]
                if isinstance(expr, ast.IfExp)
                else expr.values
                if isinstance(expr, ast.BoolOp)
                else expr.elts
            )
            return set().union(*(self.values(scope, x, depth + 1) for x in parts))
        if isinstance(expr, ast.Subscript):
            mapping = self.values(scope, expr.value, depth + 1)
            key = expr.slice.value if isinstance(expr.slice, ast.Constant) else None
            return (
                set().union(
                    *(
                        self.maps.get((m, key), set()) | self.maps.get((m, "*"), set())
                        if key is not None
                        else set().union(*(v for (owner, _), v in self.maps.items() if owner == m))
                        for m in mapping
                    )
                )
                if mapping
                else set()
            )
        if isinstance(expr, ast.Dict):
            return {f"map:{scope}:{expr.lineno}:{expr.col_offset}"}
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            try:
                if expr.value not in self.forward_refs:
                    self.forward_refs[expr.value] = ast.parse(expr.value, mode="eval").body
                return self.values(scope, self.forward_refs[expr.value], depth + 1)
            except SyntaxError:
                return set()
        return set()

    def bind(self, scope, target, values):
        """Accumulate alternatives instead of overwriting potential conditional assignments."""
        if isinstance(target, ast.Name):
            self.bindings[scope, target.id].update(values)
        elif isinstance(target, ast.Attribute):
            for owner in sorted(self.values(scope, target.value)):
                self.attrs[owner.removeprefix("instance:"), target.attr].update(values)
        elif isinstance(target, ast.Subscript):
            key = target.slice.value if isinstance(target.slice, ast.Constant) else "*"
            for mapping in sorted(self.values(scope, target.value)):
                self.maps[mapping, key].update(values)
        elif isinstance(target, (ast.Tuple, ast.List)):
            # Do not assert tuple positional precision from an aggregate union.
            for item in target.elts:
                self.bind(scope, item, values)

    def certain(self, scope, expr, seen=None):
        """Recognize uniquely bound direct syntax independently of incomplete dataflow."""
        seen = seen or set()
        key = (scope, id(expr))
        if key in seen:
            return False
        seen.add(key)
        if isinstance(expr, ast.Name):
            current = scope
            while current in self.nodes:
                values = self.bindings.get((current, expr.id), set())
                if values or expr.id in self.local_names.get(current, set()):
                    if len(values) != 1:
                        return False
                    assignments = [
                        value
                        for owner, target, value in self.assignments
                        if owner == current
                        and isinstance(target, ast.Name)
                        and target.id == expr.id
                    ]
                    if assignments:
                        return all(
                            self.certain(current, value, seen.copy()) for value in assignments
                        )
                    return bool(self.members.get((current, expr.id)))
                current = self.nodes[current]["parent"]
        if isinstance(expr, ast.Attribute):
            receiver = expr.value
            if isinstance(receiver, ast.Call):
                vals = self.values(scope, receiver.func)
                return (
                    len(vals) == 1
                    and all(self.nodes.get(v, {}).get("kind") == "class" for v in vals)
                    and self.certain(scope, receiver.func, seen)
                )
            if isinstance(receiver, ast.Name) and receiver.id in ("self", "cls"):
                owner = self.nodes.get(self.nodes[scope]["parent"], {})
                return owner.get("kind") == "class"
        return False

    def size(self):
        """Monotone fact cardinality for fixed-point termination."""
        return sum(
            len(v)
            for d in (self.bindings, self.attrs, self.maps, self.returns, self.bases)
            for v in d.values()
        )

    def build(self):
        """Resolve imports and iterate dataflow, then retain every callsite and its evidence."""
        for scope, item in self.imports:
            n = self.nodes[scope]
            mod = self.nodes[self.module_for[scope]]["qualname"]
            package = mod if n["path"].endswith("__init__.py") else mod.rpartition(".")[0]
            if isinstance(item, ast.Import):
                for alias in item.names:
                    name = alias.name if alias.asname else alias.name.split(".")[0]
                    targets = self.imported(n["repository"], name)
                    self.bindings[scope, alias.asname or name].update(targets)
                    for t in sorted(targets):
                        self.add_edge(
                            scope,
                            t,
                            "IMPORTS",
                            "boundary" if t.startswith("boundary:") else "resolved",
                            "import path and dependency binding",
                            item.lineno,
                            item.col_offset,
                            alias.name,
                        )
            else:
                prefix = item.module or ""
                if item.level:
                    parts = package.split(".")
                    prefix = ".".join(
                        parts[: len(parts) - item.level + 1] + ([prefix] if prefix else [])
                    )
                for alias in item.names:
                    mods = self.imported(n["repository"], prefix)
                    targets = self.attribute(mods, alias.name)
                    if not targets:
                        targets = self.imported(n["repository"], prefix + "." + alias.name)
                    self.bindings[scope, alias.asname or alias.name].update(targets)
                    for t in sorted(targets):
                        self.add_edge(
                            scope,
                            t,
                            "IMPORTS",
                            "boundary" if t.startswith("boundary:") else "resolved",
                            "from-import alias and dependency binding",
                            item.lineno,
                            item.col_offset,
                            prefix + "." + alias.name,
                        )
        for iteration in range(12):
            self.value_calls = 0
            self.memo.clear()
            before = self.size()
            for scope, target, ann in self.annotations:
                owner = self.nodes[scope]["parent"] if target is None else scope
                values = self.values(owner, ann)
                if target is None:
                    self.bases[scope].update(values)
                else:
                    instances = {
                        "instance:" + v if self.nodes.get(v, {}).get("kind") == "class" else v
                        for v in values
                    }
                    self.bind(scope, target, instances)
            for scope, target, expr in self.assignments:
                values = self.values(scope, expr)
                self.bind(scope, target, values)
                if isinstance(expr, ast.Dict):
                    for mapid in sorted(values):
                        for key, val in zip(expr.keys, expr.values):
                            self.maps[
                                mapid, key.value if isinstance(key, ast.Constant) else "*"
                            ].update(self.values(scope, val))
            for scope, expr in self.return_sites:
                self.returns[scope].update(self.values(scope, expr))
            for scope, call in self.call_sites:
                targets = self.values(scope, call.func)
                for t in sorted(targets):
                    function = self.asts.get(t)
                    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    params = function.args.posonlyargs + function.args.args
                    if (
                        isinstance(call.func, ast.Attribute)
                        and self.nodes.get(self.nodes[t]["parent"], {}).get("kind") == "class"
                    ):
                        params = params[1:]
                    for param, arg in zip(params, call.args):
                        self.bindings[t, param.arg].update(self.values(scope, arg))
                    for kw in call.keywords:
                        if kw.arg:
                            self.bindings[t, kw.arg].update(self.values(scope, kw.value))
            if self.size() == before:
                self.saturated = True
                break
        self.value_calls = 0
        self.memo.clear()
        for scope, values in self.bases.items():
            for value in sorted(values):
                self.add_edge(
                    scope,
                    value,
                    "INHERITS",
                    "boundary" if value.startswith("boundary:") else "resolved",
                    "base expression binding",
                    self.nodes[scope]["start"],
                )
        for scope, call in self.call_sites:
            values = self.values(scope, call.func)
            targets = {
                v
                for v in values
                if self.nodes.get(v, {}).get("kind") in ("class", "function")
                or v.startswith("boundary:")
            }
            expression = ast.unparse(call.func)[:400]
            if not targets:
                self.add_edge(
                    scope,
                    None,
                    "CALLS",
                    "unresolved",
                    "dynamic/unknown receiver, excluded builtin, or unsupported value flow",
                    call.lineno,
                    call.col_offset,
                    expression,
                )
            else:
                status = (
                    "resolved"
                    if len(targets) == 1
                    and ((self.saturated and not self.limited) or self.certain(scope, call.func))
                    else "possible"
                )
                for t in sorted(targets):
                    self.add_edge(
                        scope,
                        t,
                        "CALLS",
                        "boundary" if t.startswith("boundary:") else status,
                        "lexical/import/assignment/type/argument/mapping points-to; flow-insensitive; alternatives="
                        + str(len(targets)),
                        call.lineno,
                        call.col_offset,
                        expression,
                    )
        self.edges = list({e["edge_id"]: e for e in self.edges}.values())
        return self.edges, {
            "engine": "stdlib ast + bounded monotone points-to (no project imports)",
            "fixed_point": self.saturated,
            "analysis_limited": self.limited,
            "limits": "12 rounds, expression depth 6, 2M expression evaluations per round; limited calls are possible/unresolved",
            "iterations": iteration + 1,
            "dependency_bindings": self.cross_bindings,
            "call_sites": len(self.call_sites),
        }
