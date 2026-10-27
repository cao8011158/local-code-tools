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

_DYNAMIC = object()
CALLABLE_KINDS = frozenset(("callable", "class", "context-factory", "async-context-factory"))


@dataclass(frozen=True)
class Atom:
    """A mapped definition, receiver or finite container association."""

    kind: str
    target: str
    bound: bool = False
    receiver: str = ""
    allocation: str = ""


@dataclass(frozen=True)
class Result:
    """Known alternatives and unknown origins are independent dimensions."""

    atoms: frozenset = frozenset()
    reasons: frozenset = frozenset()
    proofs: frozenset = frozenset()

    @property
    def unknown(self):
        return bool(self.reasons)


def union(*results):
    """Combine alternatives without losing unknown contributions."""
    return Result(
        frozenset(a for r in results for a in r.atoms),
        frozenset(x for r in results for x in r.reasons),
        frozenset(p for r in results for p in r.proofs),
    )


def known(kind, target, bound=False):
    """Construct a finite syntactic alternative."""
    return Result(
        frozenset([Atom(kind, target, bound)]), proofs=frozenset(["source-value:" + kind])
    )


def unknown(reason):
    """Retain a named unresolved origin alongside known candidates."""
    return Result(reasons=frozenset([reason]))


def certified(result, rule):
    """Attach a tested semantic justification; unknown reasons are never removed."""
    return Result(result.atoms, result.reasons, result.proofs | frozenset([rule]))


def invalid(rule):
    """Prove that an attempted call has no valid target in supported syntax."""
    return Result(proofs=frozenset([rule]))


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
        self.context_sites = []
        self.temp = tempfile.TemporaryDirectory(prefix="lct-python-")
        self.root = Path(self.temp.name)
        self.paths, self.scripts, self.module_for = {}, {}, {}
        self.budget, self.limited = 20000, False
        self.recursions = 0
        self.allocations = {}
        self.coverage = {}
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
        if isinstance(obj, (ast.With, ast.AsyncWith)):
            for item in obj.items:
                self.context_sites.append((execution, obj, item.context_expr))
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
                for conditional, value in self.named_bindings(s, name, before):
                    entry = ("conditional-value" if conditional else "value", value)
                    result = result + [entry] if conditional else [entry]
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
                dict(
                    kind=a.kind,
                    target=a.target,
                    bound=a.bound,
                    receiver=a.receiver,
                    allocation=a.allocation,
                )
                for a in sorted(
                    result.atoms,
                    key=lambda a: (a.kind, a.target, a.bound, a.receiver, a.allocation),
                )
            ],
            unknown_reasons=sorted(result.reasons),
            proofs=sorted(result.proofs),
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
        if isinstance(expr, ast.NamedExpr):
            return certified(self.resolve(scope, expr.value), "ordered-named-expression")
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
                    allocation = f"{scope}:{expr.lineno}:{expr.col_offset}"
                    self.allocations[allocation] = (scope, expr)
                    results.append(
                        certified(
                            Result(frozenset([Atom("instance", a.target, allocation=allocation)])),
                            "explicit-construction-site",
                        )
                    )
                elif a.kind in ("context-factory", "async-context-factory"):
                    results.append(
                        certified(
                            known(
                                "async-context-manager"
                                if a.kind == "async-context-factory"
                                else "context-manager",
                                a.target,
                            ),
                            "verified-contextlib-wrapper",
                        )
                    )
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
                return certified(
                    union(*(self.binding(current, kind, item) for kind, item in items)),
                    "reaching-lexical-binding",
                )
            if param:
                return self.parameter(current, param)
            if self.local_bound(current, name):
                return invalid("unbound-local-before-assignment")
            parent = self.nodes[current].get("resolution_parent", self.nodes[current]["parent"])
            if parent not in self.trees:
                break
            if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                while parent in self.trees and isinstance(self.trees[parent], ast.ClassDef):
                    parent = self.nodes[parent]["parent"]
            current = parent
            if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                before = 10**9
        value = self.query(scope, anchor)
        return (
            invalid("undefined-captured-lexical-name")
            if value.reasons == frozenset(["jedi-no-result"])
            else value
        )

    def binding(self, scope, kind, item):
        """Translate a selected binding into its source association."""
        if kind == "definition":
            ident = self.owner[id(item)]
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and len(item.decorator_list) == 1
            ):
                wrapper = self.context_wrapper(scope, item.decorator_list[0])
                if wrapper:
                    return certified(known(wrapper, ident), "verified-contextlib-decorator-origin")
            if any(
                ast.unparse(d) not in ("classmethod", "staticmethod") for d in item.decorator_list
            ):
                return unknown("decorated-binding-not-modeled")
            return known("class" if isinstance(item, ast.ClassDef) else "callable", ident)
        if kind == "value":
            return self.resolve(scope, item)
        if kind == "conditional-value":
            return union(self.resolve(scope, item), unknown("conditional-named-expression"))
        if kind == "import":
            stmt, alias = item
            query = ast.Name(id=alias.asname or alias.name)
            query.lineno = query.end_lineno = alias.end_lineno
            query.col_offset = alias.col_offset
            query.end_col_offset = alias.end_col_offset
            value = self.query(scope, query, goto=True)
            atoms = []
            for atom in value.atoms:
                tree = self.trees.get(atom.target)
                kind = atom.kind
                if (
                    kind == "callable"
                    and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and len(tree.decorator_list) == 1
                ):
                    kind = (
                        self.context_wrapper(
                            self.nodes[atom.target]["parent"], tree.decorator_list[0]
                        )
                        or kind
                    )
                atoms.append(Atom(kind, atom.target, atom.bound, atom.receiver, atom.allocation))
            return Result(frozenset(atoms), value.reasons, value.proofs)
        if kind == "with":
            stmt, context = item
            receivers = self.resolve(scope, context)
            results = []
            method = "__aenter__" if isinstance(stmt, ast.AsyncWith) else "__enter__"
            for a in receivers.atoms:
                if a.kind in ("context-manager", "async-context-manager"):
                    expected = (
                        "async-context-manager"
                        if isinstance(stmt, ast.AsyncWith)
                        else "context-manager"
                    )
                    if a.kind != expected:
                        results.append(invalid("wrong-context-protocol"))
                    else:
                        results.append(self.generator_binding(a.target))
                if a.kind in ("instance", "class"):
                    for k, b in self.reaching(a.target, method, 10**9):
                        value = self.binding(a.target, k, b)
                        for target in value.atoms:
                            results.extend(
                                self.resolve(target.target, r)
                                for r in self.return_values(self.trees[target.target])
                            )
            return union(*results) if results else unknown("unsupported-context-manager")
        return (
            invalid("deleted-name-binding") if kind == "unbound" else unknown("unsupported-binding")
        )

    def attribute(self, scope, expr):
        """Apply descriptor boundaries, instance fields, then nondata class members."""
        receivers = self.resolve(scope, expr.value)
        receipt = self.coverage.setdefault(
            (scope, id(expr)), dict(rule="instance-field-coverage", events=[], complete=False)
        )
        results = []
        for receiver in receivers.atoms:
            if receiver.kind not in ("instance", "class", "module", "super"):
                continue
            value = self.member(receiver.target, expr.attr, skip_own=receiver.kind == "super")
            if receiver.kind == "instance":
                guard = self.descriptor_guard(receiver.target, expr.attr, value)
                if guard:
                    results.append(union(self.query(scope, expr), unknown(guard)))
                    continue
                if self.instance_argument_escape(receiver, scope, expr):
                    results.append(unknown("instance-argument-escape"))
                field = self.instance_field(receiver, expr.attr, scope, expr)
                if field is not None:
                    if any(a.kind == "absent-field" for a in field.atoms):
                        field = Result(
                            frozenset(a for a in field.atoms if a.kind != "absent-field"),
                            field.reasons,
                            field.proofs,
                        )
                        if value is not None:
                            fallback = frozenset(
                                Atom(
                                    a.kind,
                                    a.target,
                                    a.kind == "callable",
                                    receiver.target,
                                    receiver.allocation,
                                )
                                for a in value.atoms
                            )
                            field = union(field, Result(fallback, value.reasons, value.proofs))
                    if (
                        "conditional-instance-field-uninitialized" in field.reasons
                        and value is not None
                    ):
                        alternatives = frozenset(
                            Atom(
                                a.kind,
                                a.target,
                                a.kind == "callable",
                                receiver.target,
                                receiver.allocation,
                            )
                            for a in value.atoms
                        )
                        field = union(field, Result(alternatives, value.reasons, value.proofs))
                    results.append(certified(field, "python-instance-field-precedence"))
                    continue
            if value is not None:
                atoms = []
                for v in value.atoms:
                    obj = self.trees.get(v.target)
                    decorators = {ast.unparse(d) for d in getattr(obj, "decorator_list", [])}
                    bound = isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                        "classmethod" in decorators
                        or (
                            receiver.kind in ("instance", "super")
                            and "staticmethod" not in decorators
                        )
                    )
                    atoms.append(
                        Atom(
                            v.kind,
                            v.target,
                            bound,
                            receiver.target if bound else "",
                            receiver.allocation if bound else v.allocation,
                        )
                    )
                results.append(
                    certified(
                        Result(frozenset(atoms), value.reasons, value.proofs),
                        "python-nondata-member-lookup",
                    )
                )
        if results:
            result = union(*results, unknown("unknown-receiver") if receivers.unknown else Result())
            receipt["complete"] = not result.unknown
            return result
        result = self.query(scope, expr)
        return Result(result.atoms, result.reasons | receivers.reasons, result.proofs)

    def descriptor_guard(self, owner, name, value):
        """Refuse custom attribute hooks, data descriptors and unverified decorators."""
        if any(
            self.member(owner, n) is not None
            for n in ("__getattribute__", "__getattr__", "__setattr__", "__delattr__")
        ):
            return "dynamic-attribute-hook"
        if self.member(owner, "__new__") is not None or any(
            kw.arg == "metaclass" for kw in getattr(self.trees[owner], "keywords", [])
        ):
            return "custom-construction-protocol"
        if self.reaching(owner, "__slots__", 10**9):
            return "slotted-instance-field-not-modeled"
        if value is not None:
            if "decorated-binding-not-modeled" in value.reasons:
                return "descriptor-or-decorated-member-not-modeled"
            for atom in value.atoms:
                if atom.kind == "instance" and self.member(atom.target, "__get__") is not None:
                    if any(
                        self.member(atom.target, n) is not None for n in ("__set__", "__delete__")
                    ):
                        return "data-descriptor-protocol-not-modeled"
        return None

    def write_targets(self, statement):
        """Normalize assignment, annotated assignment and deletion without executing them."""
        if isinstance(statement, (ast.Assign, ast.Delete)):
            return statement.targets
        if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            return [statement.target]
        return []

    def field_update(self, value, statement, candidate, direct, name):
        """Apply a proven store/delete, or retain alternatives with an explicit limitation."""
        if isinstance(statement, ast.AnnAssign) and statement.value is None:
            return value
        if isinstance(statement, ast.AugAssign):
            return union(value or Result(), unknown("unsupported-instance-augassign"))
        if isinstance(statement, ast.Delete):
            candidate = known("absent-field", name)
        if direct:
            return candidate
        return union(
            value or known("absent-field", name),
            candidate or Result(),
            unknown(
                "conditional-instance-field-uninitialized"
                if value is None
                else "conditional-instance-field"
            ),
        )

    def method_field_effect(self, receiver, method, name):
        """Recognize straight-line self-field stores/deletes; never execute a method body.

        Plain references/literals and writes to other known dictionary fields are finite
        effects. Calls, branching, parameter-dependent values or dynamic targets invalidate
        the field instead of simulating cross-procedure execution.
        """
        member = self.member(receiver.target, method)
        if not member or member.unknown or len(member.atoms) != 1:
            return unknown("unresolved-receiver-method-effects")
        atom = next(iter(member.atoms))
        tree = self.trees.get(atom.target)
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)) or tree.decorator_list:
            return unknown("unsupported-receiver-method-effects")
        params = tree.args.posonlyargs + tree.args.args + tree.args.kwonlyargs
        self_name = params[0].arg if params else None
        other_params = {a.arg for a in params[1:]}
        # A class method shadowed by an instance store cannot be simulated as that
        # class definition. Preserve the boundary even if Jedi supplies a candidate.
        initializer = self.member(receiver.target, "__init__")
        if initializer:
            for init in initializer.atoms:
                if init.kind != "callable":
                    continue
                for st in self.direct_statements(self.trees[init.target]):
                    if any(
                        isinstance(t, ast.Attribute) and t.attr == method
                        for t in self.write_targets(st)
                    ) and not (isinstance(st, ast.AnnAssign) and st.value is None):
                        return unknown("shadowed-receiver-method-effects")
        value = None
        for statement in tree.body:
            targets = self.write_targets(statement)
            if not targets:
                if isinstance(statement, ast.Pass) or (
                    isinstance(statement, (ast.Expr, ast.Return))
                    and (statement.value is None or isinstance(statement.value, ast.Constant))
                ):
                    continue
                return union(value or Result(), unknown("unsupported-receiver-method-effects"))
            if isinstance(statement, ast.AnnAssign) and statement.value is None:
                continue
            rhs = getattr(statement, "value", None)
            if rhs is not None and not isinstance(rhs, (ast.Name, ast.Constant)):
                return union(value or Result(), unknown("unsupported-receiver-method-value"))
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == self_name
                ):
                    if target.attr == name:
                        if isinstance(rhs, ast.Name) and rhs.id in other_params | {self_name}:
                            return unknown("unsupported-receiver-method-value")
                        candidate = self.resolve(atom.target, rhs) if rhs else None
                        value = self.field_update(value, statement, candidate, True, name)
                elif isinstance(target, ast.Name):
                    continue
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == self_name
                ):
                    # Container slot mutations are accounted for by subscript(), not a field rebind.
                    continue
                else:
                    return union(value or Result(), unknown("unsupported-receiver-method-target"))
        return value

    def instance_field(self, receiver, name, scope, anchor):
        """Join constructor/direct field events and limited same-receiver method effects."""
        value = None
        events = self.coverage.setdefault(
            (scope, id(anchor)), dict(rule="instance-field-coverage", events=[], complete=False)
        )["events"]
        initializer = self.member(receiver.target, "__init__")
        if initializer:
            for function in initializer.atoms:
                if function.kind != "callable":
                    continue
                tree = self.trees[function.target]
                args = tree.args.posonlyargs + tree.args.args
                self_name = args[0].arg if args else None
                for stmt in self.direct_statements(tree):
                    call = (
                        stmt.value
                        if isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign))
                        else None
                    )
                    effect = None
                    if isinstance(call, ast.Call):
                        if (
                            isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == self_name
                        ):
                            effect = self.method_field_effect(receiver, call.func.attr, name)
                        elif any(
                            isinstance(n, ast.Name) and n.id == self_name
                            for arg in call.args + [k.value for k in call.keywords]
                            for n in ast.walk(arg)
                        ):
                            effect = unknown("constructor-receiver-escape")
                    if effect is not None:
                        events.append(
                            dict(
                                kind="constructor-call-effects",
                                scope=function.target,
                                line=stmt.lineno,
                            )
                        )
                        if stmt in tree.body and not effect.unknown:
                            value = effect
                        else:
                            value = union(
                                value or known("absent-field", name),
                                effect,
                                unknown("unproven-constructor-effects"),
                            )
                    for target in self.write_targets(stmt):
                        if not (
                            isinstance(target, ast.Attribute)
                            and target.attr == name
                            and isinstance(target.value, ast.Name)
                            and target.value.id == self_name
                        ):
                            continue
                        events.append(
                            dict(kind=type(stmt).__name__, scope=function.target, line=stmt.lineno)
                        )
                        rhs = getattr(stmt, "value", None)
                        candidate = (
                            self.field_value(function.target, rhs, receiver.allocation)
                            if rhs
                            else None
                        )
                        value = self.field_update(value, stmt, candidate, stmt in tree.body, name)
        for stmt in self.direct_statements(self.trees[scope]):
            if not isinstance(stmt, ast.stmt):
                continue
            if (stmt.lineno, stmt.col_offset) >= (anchor.lineno, anchor.col_offset):
                continue
            for target in self.write_targets(stmt):
                if (
                    not isinstance(target, ast.Attribute)
                    or target.attr != name
                    or not receiver.allocation
                ):
                    continue
                owners = self.resolve(scope, target.value)
                if any(
                    o.kind == "instance" and o.allocation == receiver.allocation
                    for o in owners.atoms
                ):
                    events.append(dict(kind=type(stmt).__name__, scope=scope, line=stmt.lineno))
                    rhs = getattr(stmt, "value", None)
                    candidate = self.resolve(scope, rhs) if rhs else None
                    direct = stmt in self.statements[scope] and not owners.unknown
                    value = self.field_update(value, stmt, candidate, direct, name)
            call = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign)) else None
            if (
                not isinstance(call, ast.Call)
                or not isinstance(call.func, ast.Attribute)
                or not receiver.allocation
            ):
                continue
            owners = self.resolve(scope, call.func.value)
            if not any(
                o.kind == "instance" and o.allocation == receiver.allocation for o in owners.atoms
            ):
                continue
            effect = self.method_field_effect(receiver, call.func.attr, name)
            if effect is None:
                continue
            events.append(
                dict(
                    kind="receiver-method-call",
                    method=call.func.attr,
                    scope=scope,
                    line=stmt.lineno,
                )
            )
            if stmt in self.statements[scope] and not owners.unknown and not effect.unknown:
                value = effect
            else:
                value = union(
                    value or known("absent-field", name),
                    effect,
                    unknown("unproven-receiver-method-effects"),
                )
        if value is None:
            return None
        return Result(
            frozenset(
                Atom(
                    a.kind,
                    a.target,
                    a.bound,
                    a.receiver,
                    receiver.allocation if a.kind == "container" else a.allocation,
                )
                for a in value.atoms
            ),
            value.reasons,
            value.proofs,
        )

    def field_value(self, function, expr, allocation):
        """Join a direct constructor parameter to the arguments of its creation site."""
        args = self.trees[function].args.posonlyargs + self.trees[function].args.args
        names = [p.arg for p in args]
        if isinstance(expr, ast.Name) and expr.id in names[1:]:
            origin = self.allocations.get(allocation)
            if origin:
                scope, call = origin
                supplied = {p.arg: arg for p, arg in zip(args[1:], call.args)}
                supplied.update({kw.arg: kw.value for kw in call.keywords if kw.arg})
                if any(kw.arg is None for kw in call.keywords) or any(
                    isinstance(a, ast.Starred) for a in call.args
                ):
                    return unknown("constructor-argument-unpacking")
                if expr.id in supplied:
                    return certified(
                        self.resolve(scope, supplied[expr.id]), "constructor-argument-origin"
                    )
                default = self.parameter_default(self.trees[function], expr.id)
                if default is not None:
                    return self.resolve(self.nodes[function]["parent"], default)
            return unknown("unknown-constructor-field-input")
        return self.resolve(function, expr)

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
                            certified(
                                Result(
                                    frozenset(
                                        [
                                            Atom(
                                                "class"
                                                if "classmethod" in decorators
                                                else "instance",
                                                a.receiver,
                                                allocation=a.allocation,
                                            )
                                        ]
                                    )
                                ),
                                "bound-receiver-origin",
                            )
                        )
            if receivers:
                value = union(*receivers)
                return (
                    value
                    if self.repos[self.nodes[scope]["repository"]].get("closed_world", False)
                    else union(value, unknown("open-receiver-input"))
                )
            # A lexical body without an observed invocation can still be reached by
            # explicitly constructed instances; preserve those finite origins.
            if "classmethod" not in decorators:
                for site in self.sites:
                    if site["_call"] is None:
                        continue
                    callee = self.resolve(site["execution_owner"], site["_expr"])
                    if any(a.kind == "class" and a.target == parent for a in callee.atoms):
                        allocation = f"{site['execution_owner']}:{site['_call'].lineno}:{site['_call'].col_offset}"
                        self.allocations[allocation] = (site["execution_owner"], site["_call"])
                        receivers.append(
                            certified(
                                Result(
                                    frozenset([Atom("instance", parent, allocation=allocation)])
                                ),
                                "class-construction-receiver-candidates",
                            )
                        )
            if receivers:
                value = union(*receivers)
                return (
                    value
                    if self.repos[self.nodes[scope]["repository"]].get("closed_world", False)
                    else union(value, unknown("open-receiver-input"))
                )
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
                    return certified(Result(atoms), "closed-input-annotation")
            return unknown("parameter-without-known-origin")
        return union(*results)

    def container_slots(self, atom, scope, anchor, lookup, seen=None):
        """Read a finite literal/copy snapshot, with ordered writes and explicit coverage."""
        seen = set() if seen is None else seen
        if atom.target in seen:
            return {}, set(), [unknown("recursive-dict-expansion")], []
        seen = seen | {atom.target}
        owner, obj = self.container_exprs[atom.target]
        events = []
        if atom.allocation:
            origin = self.allocations.get(atom.allocation)
            if (
                not origin
                or not isinstance(self.trees[origin[0]], ast.Module)
                or not any(
                    isinstance(stmt, ast.Assign) and stmt.value is origin[1]
                    for stmt in self.trees[origin[0]].body
                )
            ):
                return {}, set(), [unknown("nonunique-instance-container-allocation")], events
        sequence = not isinstance(obj, ast.Dict)
        slots, sealed, extra = {}, set(), []

        def uncertain(reason):
            value = unknown(reason)
            for k in list(slots):
                slots[k] = [union(*slots[k], value)]
            slots[_DYNAMIC] = [value]
            sealed.clear()

        if sequence:
            slots = {i: [self.resolve(owner, v)] for i, v in enumerate(obj.elts)}
            sealed = set(slots)
        else:
            for key, value in zip(obj.keys, obj.values):
                if key is None:
                    events.append(dict(kind="DictUnpack", scope=owner, line=value.lineno))
                    origins = self.resolve(owner, value)
                    if origins.unknown or len(origins.atoms) != 1:
                        uncertain("unknown-or-ambiguous-dict-expansion")
                    for source in origins.atoms:
                        if source.kind != "container" or not isinstance(
                            self.container_exprs[source.target][1], ast.Dict
                        ):
                            uncertain("non-dictionary-expansion-source")
                            continue
                        values, source_sealed, limitations, nested = self.container_slots(
                            source, owner, value, lookup, seen
                        )
                        events.extend(nested)
                        if _DYNAMIC in values or limitations:
                            uncertain("incomplete-dict-expansion")
                        for k, rs in values.items():
                            if k is _DYNAMIC:
                                continue
                            slots[k] = rs
                            if k in source_sealed:
                                sealed.add(k)
                else:
                    fixed, k = self.literal_key(key)
                    if fixed:
                        slots[k] = [self.resolve(owner, value)]
                        sealed.add(k)
                    else:
                        uncertain("dynamic-literal-dict-key")
        for function, tree in self.trees.items():
            if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                continue
            for statement in self.direct_statements(tree):
                if not isinstance(
                    statement, (ast.Assign, ast.AnnAssign, ast.Delete, ast.AugAssign)
                ):
                    continue
                if function == scope and (statement.lineno, statement.col_offset) >= (
                    anchor.lineno,
                    anchor.col_offset,
                ):
                    continue
                for dest in self.write_targets(statement):
                    if (
                        not isinstance(dest, ast.Subscript)
                        or atom not in self.resolve(function, dest.value).atoms
                    ):
                        continue
                    events.append(
                        dict(kind=type(statement).__name__, scope=function, line=statement.lineno)
                    )
                    if isinstance(statement, ast.AnnAssign) and statement.value is None:
                        continue
                    write_fixed, key = self.literal_key(dest.slice)
                    if sequence and write_fixed and isinstance(key, int) and key < 0:
                        key += len(slots)
                    direct = statement in tree.body and function in (scope, owner)
                    if isinstance(statement, ast.Delete):
                        if direct and write_fixed:
                            slots.pop(key, None)
                            sealed.add(key)
                            if sequence:
                                slots = {
                                    i: rs
                                    for i, rs in enumerate(rs for _, rs in sorted(slots.items()))
                                }
                        elif not write_fixed or lookup is None or lookup == key:
                            extra.append(unknown("conditional-or-dynamic-slot-deletion"))
                    elif isinstance(statement, ast.AugAssign):
                        extra.append(unknown("unsupported-slot-augassign"))
                    elif (
                        isinstance(dest.slice, ast.Name)
                        and isinstance(statement.value, ast.Name)
                        and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and function != scope
                    ):
                        extra.extend(
                            self.registry_arguments(
                                function, dest.slice.id, statement.value.id, lookup, atom.allocation
                            )
                        )
                    elif direct and write_fixed:
                        slots[key] = [self.resolve(function, statement.value)]
                        sealed.add(key)
                    elif lookup is None or not write_fixed or key == lookup:
                        extra.extend(
                            [
                                self.resolve(function, statement.value),
                                unknown("conditional-or-dynamic-slot-write"),
                            ]
                        )
            for site in self.sites:
                if site["execution_owner"] != function or site["_call"] is None:
                    continue
                if function == scope and (site["line"], site["column"]) >= (
                    anchor.lineno,
                    anchor.col_offset,
                ):
                    continue
                callee, call = site["_expr"], site["_call"]
                uses = (
                    ([callee.value] if isinstance(callee, ast.Attribute) else [])
                    + call.args
                    + [kw.value for kw in call.keywords]
                )
                if any(self.container_reachable(function, use, atom) for use in uses):
                    events.append(dict(kind="container-escape", scope=function, line=site["line"]))
                    extra.append(unknown("container-mutation-or-escape"))
        return slots, sealed, extra, events

    def subscript(self, scope, expr):
        """Resolve a slot only after the relevant ordered writes and sources are covered."""
        containers = self.resolve(scope, expr.value)
        fixed, key = self.literal_key(expr.slice)
        results, events = [], []
        for atom in containers.atoms:
            if atom.kind != "container":
                continue
            slots, sealed, extra, observed = self.container_slots(
                atom, scope, expr, key if fixed else None
            )
            events.extend(observed)
            sequence = not isinstance(self.container_exprs[atom.target][1], ast.Dict)
            lookup = key
            if sequence and fixed:
                if not isinstance(key, int):
                    results.append(invalid("invalid-literal-sequence-index"))
                    continue
                lookup = key + len(slots) if key < 0 else key
            chosen = [
                r
                for k, rs in slots.items()
                if not fixed or k == lookup or k is _DYNAMIC and lookup not in sealed
                for r in rs
            ]
            results.append(
                certified(union(*chosen, *extra), "literal-slot-state")
                if chosen or extra
                else invalid("missing-literal-slot")
            )
        if containers.unknown:
            results.append(unknown("unknown-container-origin"))
        result = union(*results) if results else unknown("unresolved-container-slot")
        self.coverage[(scope, id(expr))] = dict(
            rule="container-write-source-coverage", events=events, complete=not result.unknown
        )
        return result

    def literal_key(self, expr):
        """Read hashable constants and signed literal integers without eval."""
        if isinstance(expr, ast.Constant):
            try:
                hash(expr.value)
            except TypeError:
                return False, None
            return True, expr.value
        if (
            isinstance(expr, ast.UnaryOp)
            and isinstance(expr.op, (ast.USub, ast.UAdd))
            and isinstance(expr.operand, ast.Constant)
            and type(expr.operand.value) is int
        ):
            return True, (
                -expr.operand.value if isinstance(expr.op, ast.USub) else expr.operand.value
            )
        return False, None

    def container_reachable(self, scope, expr, target, seen=None):
        """Check explicit nested argument containers, including keyword and unpack values."""
        if isinstance(expr, ast.Starred):
            expr = expr.value
        seen = set() if seen is None else seen
        values = self.resolve(scope, expr)
        for atom in values.atoms:
            if atom == target:
                return True
            if atom.kind == "container" and atom.target not in seen:
                seen.add(atom.target)
                owner, obj = self.container_exprs[atom.target]
                parts = obj.values if isinstance(obj, ast.Dict) else obj.elts
                if any(self.container_reachable(owner, p, target, seen) for p in parts):
                    return True
        return False

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

    def registry_arguments(self, function, key_param, value_param, lookup, allocation=""):
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
                if allocation and a.allocation != allocation:
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

    def named_bindings(self, statement, name, before):
        """Select ordered walrus stores; short-circuit/conditional stores stay open."""

        def visit(obj, conditional=False):
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(obj, ast.NamedExpr):
                yield from visit(obj.value, conditional)
                if (
                    isinstance(obj.target, ast.Name)
                    and obj.target.id == name
                    and (obj.end_lineno, obj.end_col_offset) < before
                ):
                    yield conditional, obj.value
                return
            if isinstance(obj, ast.If):
                yield from visit(obj.test, conditional)
                return
            if isinstance(
                obj,
                (
                    ast.BoolOp,
                    ast.IfExp,
                    ast.comprehension,
                    ast.ListComp,
                    ast.SetComp,
                    ast.DictComp,
                    ast.GeneratorExp,
                ),
            ):
                for c in ast.iter_child_nodes(obj):
                    yield from visit(c, True)
                return
            if isinstance(
                obj, (ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)
            ):
                return
            for c in ast.iter_child_nodes(obj):
                yield from visit(c, conditional)

        return list(visit(statement))

    def context_wrapper(self, scope, decorator):
        """Accept only an exact Jedi-resolved stdlib contextlib decorator origin."""
        value = self.query(scope, decorator, goto=True)
        origins = {a.target for a in value.atoms if a.kind == "boundary"}
        if value.unknown:
            return None
        if origins == {"contextlib.contextmanager"}:
            return "context-factory"
        if origins == {"contextlib.asynccontextmanager"}:
            return "async-context-factory"
        return None

    def generator_binding(self, function):
        """Prove one straight-line yield; complex wrappers retain known yield candidates."""
        tree = self.trees[function]
        yields = [n for s in self.direct_statements(tree) for n in [s] if isinstance(n, ast.Yield)]
        values = [self.resolve(function, y.value) for y in yields if y.value is not None]
        simple = (
            len(yields) == 1
            and any(isinstance(s, ast.Expr) and s.value is yields[0] for s in tree.body)
            and all(
                isinstance(s, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Pass)) for s in tree.body
            )
            and not any(
                isinstance(n, (ast.YieldFrom, ast.Await)) for s in tree.body for n in ast.walk(s)
            )
        )
        if simple:
            return certified(union(*values), "single-straight-line-contextlib-yield")
        return union(*values, unknown("complex-generator-context-protocol"))

    def adjudicate(self, scope, expr, result, signal):
        """Require explicit proof, and explain every choice between LCT and Jedi signals."""
        chosen = {a.target for a in result.atoms if a.kind in CALLABLE_KINDS}
        inferred = {a.target for a in signal.atoms if a.kind in CALLABLE_KINDS}
        decisive = {
            "reaching-lexical-binding",
            "python-instance-field-precedence",
            "python-nondata-member-lookup",
            "literal-slot-state",
            "missing-literal-slot",
            "invalid-literal-sequence-index",
            "unbound-local-before-assignment",
            "undefined-captured-lexical-name",
            "deleted-name-binding",
            "single-straight-line-contextlib-yield",
            "bound-receiver-origin",
        }
        receipt = self.coverage.get((scope, id(expr)))
        needs_coverage = (
            isinstance(expr, ast.Subscript) or isinstance(expr, ast.Attribute) and bool(chosen)
        )
        if needs_coverage and not (receipt and receipt["complete"]) and not result.unknown:
            result = union(result, unknown("missing-write-source-coverage"))
        justified = bool(result.proofs & decisive)
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            justified = bool(receipt and receipt["complete"])
        conflict = bool(inferred and chosen != inferred)
        reason = (
            "matching-signals"
            if chosen == inferred
            else "finite-association-with-missing-jedi-signal"
        )
        if conflict:
            if justified and not result.unknown:
                reason = "tested-semantic-rule"
            elif justified or receipt and result.unknown and result.proofs:
                result = union(result, unknown("unresolved-partial-signal-conflict"))
                reason = "partial-association-conflict-retained"
            else:
                result = union(
                    Result(reasons=result.reasons), unknown("unadjudicated-jedi-lct-conflict")
                )
                reason = "unresolved-conflict-no-decisive-rule"
        if not result.proofs and not result.unknown:
            result = union(result, unknown("no-completeness-proof"))
        if not chosen and any(
            a.kind
            in ("instance", "external-value", "context-manager", "async-context-manager", "super")
            for a in result.atoms
        ):
            result = union(result, unknown("value-call-protocol-not-modeled"))
        decision = dict(
            jedi_targets=sorted(inferred),
            lct_targets=sorted(chosen),
            selected_targets=sorted(a.target for a in result.atoms if a.kind in CALLABLE_KINDS),
            conflict=conflict,
            reason=reason,
            semantic_rules=sorted(result.proofs),
            write_source_coverage=receipt,
            excluded_jedi_targets=sorted(inferred - {a.target for a in result.atoms})
            if reason == "tested-semantic-rule"
            else [],
            unresolved_jedi_targets=sorted(inferred - {a.target for a in result.atoms})
            if reason != "tested-semantic-rule"
            else [],
            excluded_lct_targets=sorted(chosen - {a.target for a in result.atoms}),
        )
        return result, decision

    def instance_argument_escape(self, receiver, scope, anchor):
        """Do not certify a field after its receiver is passed to another call."""
        if not receiver.allocation:
            return False
        for site in self.sites:
            if site["execution_owner"] != scope or site["_call"] is None:
                continue
            if (site["line"], site["column"]) >= (anchor.lineno, anchor.col_offset):
                continue
            call = site["_call"]
            for arg in call.args + [kw.value for kw in call.keywords]:
                values = self.resolve(scope, arg.value if isinstance(arg, ast.Starred) else arg)
                if any(
                    a.kind == "instance" and a.allocation == receiver.allocation
                    for a in values.atoms
                ):
                    return True
        return False
