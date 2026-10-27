"""Captured-source Jedi bridge with finite lexical/callback/container associations.

No analyzed module is imported. This is not a Python executor or iterative type
engine: unsupported mutation and control flow contribute explicit unknown origins.
"""

import ast
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import jedi

from .common import canonical, digest


@dataclass(frozen=True)
class Atom:
    """A mapped definition, receiver or finite container association."""

    kind: str
    target: str
    bound: bool = False
    receiver: str = ""


@dataclass(frozen=True)
class Result:
    """Known alternatives and unknown origins are independent dimensions."""

    atoms: frozenset = frozenset()
    reasons: frozenset = frozenset()

    @property
    def unknown(self):
        return bool(self.reasons)


def union(*results):
    """Combine alternatives without losing unknown contributions."""
    return Result(
        frozenset(a for r in results for a in r.atoms),
        frozenset(x for r in results for x in r.reasons),
    )


def known(kind, target, bound=False):
    """Construct a finite syntactic alternative."""
    return Result(frozenset([Atom(kind, target, bound)]))


def unknown(reason):
    """Retain a named unresolved origin alongside known candidates."""
    return Result(reasons=frozenset([reason]))


class Analyzer:
    """Resolve one private source capture with recursion and work budgets."""

    def __init__(self, nodes, trees, repos, imported):
        self.nodes, self.trees, self.repos = nodes, trees, repos
        self.imported = imported
        self.owner = {id(t): ident for ident, t in trees.items()}
        self.modules = {i: t for i, t in trees.items() if isinstance(t, ast.Module)}
        self.statements = {
            i: t.body if not isinstance(t, ast.Lambda) else [] for i, t in trees.items()
        }
        self.queries, self.memo, self.container_exprs = {}, {}, {}
        self.active = set()
        self.stack, self.traces, self.dependencies = [], {}, {}
        self.sites, self.references, self.import_sites, self.inheritance = [], [], [], []
        self.temp = tempfile.TemporaryDirectory(prefix="lct-python-")
        self.root = Path(self.temp.name)
        self.paths, self.scripts, self.module_for = {}, {}, {}
        self.budget, self.limited = 20000, False
        self.recursions = 0
        for ident, t in self.modules.items():
            n = nodes[ident]
            path = self.root / n["repository"] / n["path"]
            if not path.resolve().is_relative_to(self.root):
                raise ValueError("Source path escapes captured workspace")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(t._lct_source, encoding="utf-8")
            self.paths[path.resolve()] = ident
        roots = set()
        for path, ident in self.paths.items():
            mod = nodes[ident]["qualname"]
            depth = len(mod.split(".")) if path.name == "__init__.py" else len(mod.split(".")) - 1
            root = path.parent
            for _ in range(depth):
                root = root.parent
            roots.add(str(root))
        library_paths = [
            p
            for p in sys.path
            if p
            and ("site-packages" in p or "python" in p.lower())
            and str(Path(p).resolve()) != str(Path.cwd().resolve())
        ]
        project = jedi.Project(
            self.root,
            sys_path=sorted(roots) + library_paths,
            smart_sys_path=False,
            load_unsafe_extensions=False,
        )
        for path, ident in self.paths.items():
            self.scripts[ident] = jedi.Script(
                code=trees[ident]._lct_source, path=path, project=project
            )
        for ident in trees:
            mod = ident
            while nodes[mod]["kind"] != "module":
                mod = nodes[mod]["parent"]
            self.module_for[ident] = mod
        for ident, tree in self.modules.items():
            deferred = any(
                isinstance(s, ast.ImportFrom)
                and s.module == "__future__"
                and any(a.name == "annotations" for a in s.names)
                for s in tree.body
            )
            self.inventory(tree, ident, ident, "module", deferred)

    def close(self):
        """Release only this analyzer's private captured sources."""
        self.temp.cleanup()

    def inventory(self, obj, lexical, execution, phase, deferred):
        """Record syntax positions and definition-time execution owners."""
        if id(obj) in self.owner and not isinstance(obj, ast.Module):
            ident = self.owner[id(obj)]
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in obj.decorator_list:
                    self.inventory(d, ident, execution, "definition", deferred)
                    self.sites.append(
                        self.site(d, ident, execution, "definition", "implicit_decorator")
                    )
                if isinstance(obj, ast.ClassDef):
                    for base in obj.bases:
                        self.inheritance.append((ident, execution, base))
                        self.inventory(base, ident, execution, "definition", deferred)
                    for kw in obj.keywords:
                        self.inventory(kw.value, ident, execution, "definition", deferred)
                    for s in obj.body:
                        self.inventory(s, ident, ident, "class_body", deferred)
                else:
                    self.header(obj, ident, execution, deferred)
                    for s in obj.body:
                        self.inventory(s, ident, ident, "body", deferred)
                return
            if isinstance(obj, ast.Lambda):
                self.header(obj, ident, execution, deferred)
                self.inventory(obj.body, ident, ident, "body", deferred)
                return
        if isinstance(obj, ast.Call):
            self.sites.append(self.site(obj.func, lexical, execution, phase, "call", obj))
        if isinstance(obj, (ast.Import, ast.ImportFrom)):
            self.import_sites.append((execution, obj))
        if isinstance(obj, (ast.Name, ast.Attribute)) and isinstance(obj.ctx, ast.Load):
            self.references.append((execution, obj, phase))
        if isinstance(obj, ast.AnnAssign):
            if obj.value:
                self.inventory(obj.value, lexical, execution, phase, deferred)
            if not deferred and isinstance(self.trees[execution], (ast.Module, ast.ClassDef)):
                self.inventory(obj.annotation, lexical, execution, "annotation", deferred)
            return
        for child in ast.iter_child_nodes(obj):
            self.inventory(child, lexical, execution, phase, deferred)

    def header(self, obj, ident, execution, deferred):
        """Defaults run at definition; local and deferred annotations do not run."""
        for d in obj.args.defaults + [d for d in obj.args.kw_defaults if d is not None]:
            self.inventory(d, ident, execution, "definition", deferred)
        if not deferred:
            args = obj.args.posonlyargs + obj.args.args + obj.args.kwonlyargs
            for arg in args + [a for a in (obj.args.vararg, obj.args.kwarg) if a]:
                if arg.annotation:
                    self.inventory(arg.annotation, ident, execution, "annotation", deferred)
            if getattr(obj, "returns", None):
                self.inventory(obj.returns, ident, execution, "annotation", deferred)

    def site(self, expr, lexical, execution, phase, kind, call=None):
        """AST columns are UTF-8 byte offsets, converted at the Jedi boundary."""
        n = self.nodes[self.module_for[execution]]
        key = [
            n["repository"],
            n["path"],
            n["snapshot_id"],
            expr.lineno,
            expr.col_offset,
            expr.end_lineno,
            expr.end_col_offset,
            kind,
        ]
        return dict(
            site_id=digest(canonical(key)),
            lexical_owner=lexical,
            execution_owner=execution,
            phase=phase,
            kind=kind,
            line=expr.lineno,
            column=expr.col_offset,
            end_line=expr.end_lineno,
            end_column=expr.end_col_offset,
            expression=ast.unparse(expr),
            _expr=expr,
            _call=call,
        )

    def map_name(self, name):
        """Validate captured path, exact name-token position and kind, never similar names."""
        raw = dict(
            name=name.name,
            full_name=name.full_name,
            type=name.type,
            line=name.line,
            column=name.column,
            module_path=str(name.module_path) if name.module_path else None,
        )
        path = Path(name.module_path).resolve() if name.module_path else None
        module = self.paths.get(path)
        if not module:
            if not name.module_path and not name.full_name:
                raw["mapping"] = "unlocatable-jedi-result"
                return unknown("unlocatable-jedi-result"), raw
            raw["mapping"] = "external-or-excluded"
            kind = (
                "boundary"
                if name.type in ("function", "class")
                else "external-module"
                if name.type == "module"
                else "external-value"
            )
            value = known(kind, name.full_name or name.name)
            if kind == "external-value":
                value = union(value, unknown("external-value-callability-unknown"))
            return value, raw
        raw["module_path"] = self.nodes[module]["repository"] + "/" + self.nodes[module]["path"]
        raw["source_sha256"] = self.nodes[module]["source_sha256"]
        if name.type == "module":
            raw["mapping"] = "exact-captured-module"
            return known("module", module), raw
        lines = self.trees[module]._lct_source.splitlines()
        col = len(lines[name.line - 1][: name.column].encode("utf-8")) if name.line else None
        matches = []
        for ident, node in self.nodes.items():
            if self.module_for.get(ident) != module or node["definition_line"] != name.line:
                continue
            obj = self.trees.get(ident)
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                prefix = (
                    "async def "
                    if isinstance(obj, ast.AsyncFunctionDef)
                    else "def "
                    if isinstance(obj, ast.FunctionDef)
                    else "class "
                )
                if (
                    node["name"] == name.name
                    and obj.col_offset + len(prefix) == col
                    and name.type in ("function", "class", "instance")
                ):
                    matches.append(ident)
            elif isinstance(obj, ast.Lambda) and col == obj.col_offset:
                matches.append(ident)
        if not matches and name.type == "statement":
            # Imported variables are not declarations. Follow only their exact captured
            # assignment token, retaining that location as mapping evidence.
            for scope, tree in self.trees.items():
                if self.module_for[scope] != module or isinstance(tree, ast.Lambda):
                    continue
                for statement in self.direct_statements(tree):
                    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        targets = (
                            statement.targets
                            if isinstance(statement, ast.Assign)
                            else [statement.target]
                        )
                        if any(
                            isinstance(t, ast.Name)
                            and t.id == name.name
                            and t.lineno == name.line
                            and t.col_offset == col
                            for t in targets
                        ):
                            raw["mapping"] = "exact-captured-assignment"
                            return self.resolve(scope, statement.value), raw
        if len(matches) != 1:
            raw["mapping"] = (
                "ambiguous-captured-definition" if matches else "unmapped-captured-definition"
            )
            return unknown(raw["mapping"]), raw
        target = matches[0]
        raw.update(
            mapping="exact-captured-definition",
            target=target,
            version_id=self.nodes[target]["version_id"],
            repository=self.nodes[module]["repository"],
        )
        kind = (
            "instance"
            if name.type == "instance"
            else "class"
            if self.nodes[target]["kind"] == "class"
            else "callable"
        )
        return known(kind, target), raw

    def query(self, scope, expr, goto=False):
        """Preserve tool failures and every raw definition mapping."""
        module = self.module_for[scope]
        key = (module, expr.end_lineno, expr.end_col_offset, goto)
        if key in self.queries:
            return self.queries[key][0]
        line = self.trees[module]._lct_source.splitlines()[expr.end_lineno - 1]
        column = len(line.encode("utf-8")[: expr.end_col_offset].decode("utf-8"))
        raw, results = [], []
        try:
            script = self.scripts[module]
            names = (
                script.goto(expr.end_lineno, column, follow_imports=True)
                if goto
                else script.infer(expr.end_lineno, column)
            )
            for name in names:
                value, record = self.map_name(name)
                if (
                    record.get("target")
                    and record.get("repository") != self.nodes[module]["repository"]
                ):
                    target_mod = self.nodes[self.module_for[record["target"]]]["qualname"]
                    allowed = self.imported(self.nodes[module]["repository"], target_mod)
                    if self.module_for[record["target"]] not in allowed:
                        value = known("boundary", "dependency-version-unmatched:" + target_mod)
                        record["mapping"] = "dependency-version-unmatched"
                raw.append(record)
                results.append(value)
        except Exception as exc:
            raw.append(dict(error=type(exc).__name__, mapping="jedi-error"))
            results.append(unknown("jedi-error:" + type(exc).__name__))
        result = union(*results) if results else unknown("jedi-no-result")
        if not goto and any(a.kind in ("callable", "class", "instance") for a in result.atoms):
            result = union(result, unknown("jedi-inference-not-exhaustive"))
        self.queries[key] = result, raw
        return result

    def reaching(self, scope, name, before):
        """Select one name's reaching bindings, killing unconditional older values.

        If alternatives are unioned. Loops/try/match writes remain unknown. There is
        no execution environment, path simulation, heap or convergence algorithm.
        """
        before = (before, 10**9) if isinstance(before, int) else before

        def scan(body, previous):
            result = previous
            for s in body:
                if (s.lineno, s.col_offset) >= before:
                    break
                if (
                    isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and s.name == name
                ):
                    result = [("definition", s)]
                elif isinstance(s, (ast.Assign, ast.AnnAssign)):
                    targets = s.targets if isinstance(s, ast.Assign) else [s.target]
                    if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                        result = [("value", s.value)] if s.value else [("unknown", s)]
                elif isinstance(s, (ast.Import, ast.ImportFrom)):
                    for a in s.names:
                        binding = a.asname or (
                            a.name.split(".")[0] if isinstance(s, ast.Import) else a.name
                        )
                        if binding == name:
                            result = [("import", (s, a))]
                elif isinstance(s, ast.If):
                    if before[0] <= s.end_lineno:
                        for branch in (s.body, s.orelse):
                            if branch and (branch[0].lineno, branch[0].col_offset) <= before <= (
                                branch[-1].end_lineno,
                                branch[-1].end_col_offset,
                            ):
                                result = scan(branch, result)
                                break
                    else:
                        result = scan(s.body, result) + scan(s.orelse, result)
                elif isinstance(s, (ast.With, ast.AsyncWith)):
                    for item in s.items:
                        if (
                            isinstance(item.optional_vars, ast.Name)
                            and item.optional_vars.id == name
                        ):
                            result = [("with", (s, item.context_expr))]
                    result = scan(s.body, result)
                elif isinstance(s, ast.Delete):
                    if any(isinstance(t, ast.Name) and t.id == name for t in s.targets):
                        result = [("unbound", s)]
                elif isinstance(s, (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)):
                    if any(
                        isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store) and t.id == name
                        for t in ast.walk(s)
                    ):
                        result = result + [("unknown", s)]
            return result

        return scan(self.statements[scope], [])

    def local_bound(self, scope, name):
        """Python determines function locals for the whole body before execution."""
        t = self.trees[scope]
        if not isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        args = t.args.posonlyargs + t.args.args + t.args.kwonlyargs
        if name in [a.arg for a in args] + [a.arg for a in (t.args.vararg, t.args.kwarg) if a]:
            return True

        def visit(obj):
            if isinstance(obj, (ast.Global, ast.Nonlocal)) and name in obj.names:
                return -1
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return int(obj.name == name)
            if isinstance(obj, ast.Lambda):
                return 0
            if (
                isinstance(obj, ast.Name)
                and isinstance(obj.ctx, (ast.Store, ast.Del))
                and obj.id == name
            ):
                return 1
            if isinstance(obj, (ast.Import, ast.ImportFrom)):
                return int(any((a.asname or a.name.split(".")[0]) == name for a in obj.names))
            vals = [visit(c) for c in ast.iter_child_nodes(obj)]
            return -1 if -1 in vals else int(1 in vals)

        vals = [visit(s) for s in (t.body if not isinstance(t, ast.Lambda) else [t.body])]
        return -1 not in vals and 1 in vals

    def resolve(self, scope, expr, before=None):
        """Use finite associations where defined and Jedi otherwise."""
        if expr is None:
            return unknown("missing-value")
        before = before if before is not None else (expr.lineno, expr.col_offset)
        key = (scope, id(expr), before)
        if self.stack:
            deps = self.dependencies.setdefault(self.stack[-1], [])
            if key not in deps:
                deps.append(key)
        if key in self.memo:
            return self.memo[key]
        if key in self.active:
            self.recursions += 1
            return unknown("recursive-association")
        if len(self.active) >= 40 or self.budget <= 0:
            self.limited = True
            return unknown("association-budget")
        self.budget -= 1
        self.active.add(key)
        self.stack.append(key)
        recursion_before = self.recursions
        try:
            result = self._resolve(scope, expr, before)
        finally:
            self.stack.pop()
            self.active.remove(key)
        self.traces[key] = dict(
            scope=scope,
            path=self.nodes[scope]["path"],
            line=expr.lineno,
            column=expr.col_offset,
            expression=ast.unparse(expr),
            rule=type(expr).__name__,
            alternatives=[
                dict(kind=a.kind, target=a.target, bound=a.bound, receiver=a.receiver)
                for a in sorted(result.atoms, key=lambda a: (a.kind, a.target, a.bound, a.receiver))
            ],
            unknown_reasons=sorted(result.reasons),
        )
        # Never memoize an answer computed under a cut recursive dependency.
        if self.recursions == recursion_before:
            self.memo[key] = result
        return result

    def _resolve(self, scope, expr, before):
        """Only explicit syntax associations are specialized."""
        if isinstance(expr, ast.Constant):
            return known("literal", repr(expr.value))
        if isinstance(expr, ast.Lambda):
            return known("callable", self.owner[id(expr)])
        if isinstance(expr, ast.Name):
            return self.name(scope, expr.id, before, expr)
        if isinstance(expr, ast.IfExp):
            return union(self.resolve(scope, expr.body), self.resolve(scope, expr.orelse))
        if isinstance(expr, (ast.Dict, ast.List, ast.Tuple)):
            key = scope + ":" + str(expr.lineno) + ":" + str(expr.col_offset)
            self.container_exprs[key] = scope, expr
            return known("container", key)
        if isinstance(expr, ast.Subscript):
            return self.subscript(scope, expr)
        if isinstance(expr, ast.Attribute):
            return self.attribute(scope, expr)
        if isinstance(expr, ast.Call):
            if (
                isinstance(expr.func, ast.Name)
                and expr.func.id == "super"
                and not expr.args
                and not expr.keywords
            ):
                parent = self.nodes[scope]["parent"]
                if parent in self.trees and isinstance(self.trees[parent], ast.ClassDef):
                    return known("super", parent)
            targets = self.resolve(scope, expr.func)
            results = []
            for a in targets.atoms:
                if a.kind == "class":
                    results.append(known("instance", a.target))
                elif a.kind == "callable":
                    obj = self.trees[a.target]
                    returns = [obj.body] if isinstance(obj, ast.Lambda) else self.return_values(obj)
                    results.extend(self.resolve(a.target, r) for r in returns)
            if results:
                return union(
                    *results, unknown("unknown-call-result") if targets.unknown else Result()
                )
            return self.query(scope, expr)
        return self.query(scope, expr)

    def return_values(self, obj):
        """Collect direct return expressions without entering nested definitions."""
        out = []

        def visit(n):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(n, ast.Return) and n.value:
                out.append(n.value)
            for c in ast.iter_child_nodes(n):
                visit(c)

        for s in obj.body:
            visit(s)
        return out

    def name(self, scope, name, before, anchor):
        """Resolve lexical names; method bodies skip class namespaces."""
        current = scope
        while current in self.trees:
            t = self.trees[current]
            args = (
                t.args.posonlyargs + t.args.args + t.args.kwonlyargs
                if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                else []
            )
            param = next((a for a in args if a.arg == name), None)
            items = self.reaching(current, name, before)
            if items:
                return union(*(self.binding(current, kind, item) for kind, item in items))
            if param:
                return self.parameter(current, param)
            if self.local_bound(current, name):
                return Result()
            parent = self.nodes[current]["parent"]
            if parent not in self.trees:
                break
            if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                while parent in self.trees and isinstance(self.trees[parent], ast.ClassDef):
                    parent = self.nodes[parent]["parent"]
            current = parent
            before = 10**9
        value = self.query(scope, anchor)
        return Result() if value.reasons == frozenset(["jedi-no-result"]) else value

    def binding(self, scope, kind, item):
        """Translate a selected binding into its source association."""
        if kind == "definition":
            ident = self.owner[id(item)]
            if any(
                ast.unparse(d) not in ("classmethod", "staticmethod") for d in item.decorator_list
            ):
                return unknown("decorated-binding-not-modeled")
            return known("class" if isinstance(item, ast.ClassDef) else "callable", ident)
        if kind == "value":
            return self.resolve(scope, item)
        if kind == "import":
            stmt, alias = item
            query = ast.Name(id=alias.asname or alias.name)
            query.lineno = query.end_lineno = alias.end_lineno
            query.col_offset = alias.col_offset
            query.end_col_offset = alias.end_col_offset
            return self.query(scope, query, goto=True)
        if kind == "with":
            stmt, context = item
            receivers = self.resolve(scope, context)
            results = []
            method = "__aenter__" if isinstance(stmt, ast.AsyncWith) else "__enter__"
            for a in receivers.atoms:
                if a.kind in ("instance", "class"):
                    for k, b in self.reaching(a.target, method, 10**9):
                        value = self.binding(a.target, k, b)
                        for target in value.atoms:
                            results.extend(
                                self.resolve(target.target, r)
                                for r in self.return_values(self.trees[target.target])
                            )
            return union(*results) if results else unknown("unsupported-context-manager")
        return Result() if kind == "unbound" else unknown("unsupported-binding")

    def attribute(self, scope, expr):
        """Retain method binding through variable aliases and honor member replacements."""
        receivers = self.resolve(scope, expr.value)
        results = []
        for a in receivers.atoms:
            if a.kind in ("instance", "class", "module", "super"):
                value = self.member(a.target, expr.attr, skip_own=a.kind == "super")
                if value is not None:
                    atoms = []
                    for v in value.atoms:
                        obj = self.trees.get(v.target)
                        decorators = {ast.unparse(d) for d in getattr(obj, "decorator_list", [])}
                        bound = isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                            "classmethod" in decorators
                            or (
                                a.kind in ("instance", "super") and "staticmethod" not in decorators
                            )
                        )
                        atoms.append(Atom(v.kind, v.target, bound, a.target if bound else ""))
                    results.append(Result(frozenset(atoms), value.reasons))
        if results:
            return union(*results, unknown("unknown-receiver") if receivers.unknown else Result())
        result = self.query(scope, expr)
        atoms = []
        for a in result.atoms:
            obj = self.trees.get(a.target)
            decorators = {ast.unparse(d) for d in getattr(obj, "decorator_list", [])}
            bound = a.kind == "callable" and (
                "classmethod" in decorators
                or (
                    "staticmethod" not in decorators
                    and any(r.kind == "instance" for r in receivers.atoms)
                )
            )
            atoms.append(Atom(a.kind, a.target, bound))
        if not any(a.kind in ("callable", "class", "container", "instance") for a in atoms):
            # Existing instance registries commonly initialize one literal field in
            # __init__. Associate that exact field only; do not model arbitrary heaps.
            for receiver in receivers.atoms:
                if receiver.kind != "instance":
                    continue
                for kind, definition in self.reaching(receiver.target, "__init__", 10**9):
                    if kind != "definition":
                        continue
                    function = self.owner[id(definition)]
                    for statement in self.direct_statements(definition):
                        if not isinstance(statement, ast.Assign):
                            continue
                        if any(
                            isinstance(dest, ast.Attribute)
                            and dest.attr == expr.attr
                            and isinstance(dest.value, ast.Name)
                            and dest.value.id == "self"
                            for dest in statement.targets
                        ):
                            results.append(self.resolve(function, statement.value))
            if results:
                return union(
                    *results, unknown("unknown-receiver") if receivers.unknown else Result()
                )
        return Result(frozenset(atoms), result.reasons | receivers.reasons)

    def parameter(self, scope, param):
        """Associate explicit callers, keeping receiver offset and open input provenance."""
        t = self.trees[scope]
        params = t.args.posonlyargs + t.args.args
        parent = self.nodes[scope]["parent"]
        decorators = {ast.unparse(d) for d in getattr(t, "decorator_list", [])}
        if (
            parent in self.trees
            and isinstance(self.trees[parent], ast.ClassDef)
            and params
            and params[0] is param
            and "staticmethod" not in decorators
        ):
            receivers = []
            for site in self.sites:
                if site["_call"] is None or not self.may_call(scope, site):
                    continue
                for a in self.resolve(site["execution_owner"], site["_expr"]).atoms:
                    if a.kind == "callable" and a.target == scope and a.bound and a.receiver:
                        receivers.append(
                            known(
                                "class" if "classmethod" in decorators else "instance", a.receiver
                            )
                        )
            if receivers:
                return union(*receivers)
            value = known("class" if "classmethod" in decorators else "instance", parent)
            return (
                value
                if self.repos[self.nodes[scope]["repository"]].get("closed_world", False)
                else union(value, unknown("open-receiver-input"))
            )
        results = []
        for site in self.sites:
            call = site["_call"]
            if call is None or not self.may_call(scope, site):
                continue
            targets = self.resolve(site["execution_owner"], site["_expr"])
            for a in targets.atoms:
                if a.target != scope or a.kind != "callable":
                    continue
                positional = params[1:] if a.bound else params
                index = next((i for i, p in enumerate(positional) if p.arg == param.arg), None)
                arg = call.args[index] if index is not None and index < len(call.args) else None
                if isinstance(arg, ast.Starred) or any(kw.arg is None for kw in call.keywords):
                    results.append(unknown("argument-unpacking"))
                else:
                    arg = next((kw.value for kw in call.keywords if kw.arg == param.arg), arg)
                    if arg is not None:
                        results.append(self.resolve(site["execution_owner"], arg))
                    else:
                        default = self.parameter_default(t, param.arg)
                        if default is not None:
                            results.append(self.resolve(self.nodes[scope]["parent"], default))
                        else:
                            results.append(unknown("missing-required-argument"))
        if not self.repos[self.nodes[scope]["repository"]].get("closed_world", False):
            results.append(unknown("open-project-input"))
        if not results:
            if param.annotation:
                inferred = self.resolve(self.nodes[scope]["parent"], param.annotation, 10**9)
                atoms = frozenset(
                    Atom("instance", a.target) for a in inferred.atoms if a.kind == "class"
                )
                if atoms:
                    return Result(atoms)
            return unknown("parameter-without-known-origin")
        return union(*results)

    def subscript(self, scope, expr):
        """Associate slots, ordered direct overwrites and correlated registry writes."""
        containers = self.resolve(scope, expr.value)
        key = expr.slice.value if isinstance(expr.slice, ast.Constant) else None
        results = []
        for a in containers.atoms:
            if a.kind != "container":
                continue
            owner, obj = self.container_exprs[a.target]
            owner_parent = self.nodes[owner]["parent"]
            if self.nodes[owner]["name"] == "__init__" and owner_parent in self.trees:
                constructors = sum(
                    any(
                        v.kind == "class" and v.target == owner_parent
                        for v in self.resolve(site["execution_owner"], site["_expr"]).atoms
                    )
                    for site in self.sites
                    if site["_call"] is not None
                )
                if constructors > 1:
                    results.append(unknown("separate-instance-containers-not-modeled"))
                    continue
            entries = (
                [
                    (k.value if isinstance(k, ast.Constant) else None, v)
                    for k, v in zip(obj.keys, obj.values)
                ]
                if isinstance(obj, ast.Dict)
                else list(enumerate(obj.elts))
            )
            slots = {}
            for k, v in entries:
                slots[k] = [self.resolve(owner, v)]
            extra = []
            for function, tree in self.trees.items():
                if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    continue
                for statement in self.direct_statements(tree):
                    if not isinstance(statement, ast.Assign):
                        continue
                    if function == scope and (statement.lineno, statement.col_offset) >= (
                        expr.lineno,
                        expr.col_offset,
                    ):
                        continue
                    for dest in statement.targets:
                        if not isinstance(dest, ast.Subscript):
                            continue
                        dst = self.resolve(function, dest.value)
                        if a not in dst.atoms:
                            continue
                        write_key = (
                            dest.slice.value if isinstance(dest.slice, ast.Constant) else None
                        )
                        if (
                            isinstance(dest.slice, ast.Name)
                            and isinstance(statement.value, ast.Name)
                            and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and function != scope
                        ):
                            extra.extend(
                                self.registry_arguments(
                                    function, dest.slice.id, statement.value.id, key
                                )
                            )
                        elif (
                            write_key is not None
                            and statement in tree.body
                            and function in (scope, owner)
                        ):
                            slots[write_key] = [self.resolve(function, statement.value)]
                        elif key is None or write_key is None or key == write_key:
                            extra.append(self.resolve(function, statement.value))
                # Unsupported methods and escapes may introduce additional values. Merely
                # finding old literal entries cannot prove completeness after such a call.
                for site in self.sites:
                    if site["execution_owner"] != function or site["_call"] is None:
                        continue
                    callee = site["_expr"]
                    call = site["_call"]
                    if function == scope and (site["line"], site["column"]) >= (
                        expr.lineno,
                        expr.col_offset,
                    ):
                        continue
                    uses = ([callee.value] if isinstance(callee, ast.Attribute) else []) + call.args
                    for use in uses:
                        if isinstance(use, ast.Starred):
                            extra.append(unknown("container-unpacking"))
                            continue
                        if a in self.resolve(function, use).atoms:
                            extra.append(unknown("container-mutation-or-escape"))
            results.extend(
                r
                for k, values in slots.items()
                if key is None or k is None or key == k
                for r in values
            )
            results.extend(extra)
        if containers.unknown:
            results.append(unknown("unknown-container-origin"))
        return union(*results) if results else unknown("unresolved-container-slot")

    def direct_statements(self, tree):
        """Traverse lexical statements without entering nested definitions."""

        def walk(s):
            yield s
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            for c in ast.iter_child_nodes(s):
                yield from walk(c)

        for s in tree.body:
            yield from walk(s)

    def registry_arguments(self, function, key_param, value_param, lookup):
        """Join key/value arguments from the same explicit registration call."""
        results = []
        params = self.trees[function].args.posonlyargs + self.trees[function].args.args
        for site in self.sites:
            call = site["_call"]
            if call is None or not self.may_call(function, site):
                continue
            targets = self.resolve(site["execution_owner"], site["_expr"])
            for a in targets.atoms:
                if a.target != function or a.kind != "callable":
                    continue
                positional = params[1:] if a.bound else params
                supplied = {p.arg: arg for p, arg in zip(positional, call.args)}
                supplied.update({kw.arg: kw.value for kw in call.keywords if kw.arg})
                key = supplied.get(key_param)
                value = supplied.get(value_param)
                if value is None:
                    results.append(unknown("registry-missing-value"))
                    continue
                actual = key.value if isinstance(key, ast.Constant) else None
                if lookup is None or actual is None or lookup == actual:
                    results.append(self.resolve(site["execution_owner"], value))
        if not self.repos[self.nodes[function]["repository"]].get("closed_world", False):
            results.append(unknown("open-registry-writes"))
        return results

    def member(self, owner, name, skip_own=False, seen=None):
        """Use exact owned bindings or a single explicit base; complex MRO stays open."""
        seen = set() if seen is None else seen
        if owner in seen:
            return unknown("cyclic-base")
        seen.add(owner)
        items = [] if skip_own else self.reaching(owner, name, 10**9)
        if items:
            return union(*(self.binding(owner, k, item) for k, item in items))
        tree = self.trees[owner]
        if not isinstance(tree, ast.ClassDef):
            return None
        results = []
        for base in tree.bases:
            values = self.resolve(self.nodes[owner]["parent"], base)
            for a in values.atoms:
                if a.kind == "class":
                    value = self.member(a.target, name, seen=seen.copy())
                    if value is not None:
                        results.append(value)
            if values.unknown:
                results.append(unknown("unknown-base"))
        if len(tree.bases) > 1:
            results.append(unknown("multiple-inheritance-requires-jedi"))
        return union(*results) if results else None

    def may_call(self, function, site):
        """Cheap Jedi/name gate avoids recursively exploring unrelated parameter calls.

        It is only a work filter: every admitted candidate is subsequently resolved and
        compared by exact node identity. Missing or failed Jedi observations are admitted
        conservatively, preserving AST-only associations and explicit budget limits.
        """
        expr = site["_expr"]
        name = (
            expr.id
            if isinstance(expr, ast.Name)
            else expr.attr
            if isinstance(expr, ast.Attribute)
            else None
        )
        if name == self.nodes[function]["name"]:
            return True
        signal = self.query(site["execution_owner"], expr)
        if any(a.target == function for a in signal.atoms):
            return True
        return not signal.atoms

    def parameter_default(self, function, name):
        """Locate the source expression supplying a positional or keyword-only default."""
        positional = function.args.posonlyargs + function.args.args
        pairs = list(
            zip(positional[len(positional) - len(function.args.defaults) :], function.args.defaults)
        )
        pairs += list(zip(function.args.kwonlyargs, function.args.kw_defaults))
        return next((value for param, value in pairs if param.arg == name), None)

    def explain(self, scope, expr):
        """Export bounded, source-located association evidence without internal AST ids."""
        root = (scope, id(expr), (expr.lineno, expr.col_offset))
        pending, seen, steps = [root], set(), []
        while pending and len(steps) < 100:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            if key in self.traces:
                steps.append(self.traces[key])
            pending.extend(reversed(self.dependencies.get(key, [])))
        return dict(steps=steps, truncated=bool(pending))
