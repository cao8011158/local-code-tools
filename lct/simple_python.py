"""Fail-closed syntax certificate for bounded Python file components."""

import ast

from .extract import module_name
from .graph import Graph

CERTIFICATE = "simple-python-v4"
_EXPRESSIONS = (ast.Name, ast.Constant, ast.Call, ast.keyword, ast.Attribute,
                ast.Load, ast.Store, ast.BoolOp, ast.And, ast.Compare, ast.Is,
                ast.IsNot, ast.Eq, ast.LtE, ast.Subscript, ast.Set, ast.BinOp,
                ast.Pow, ast.Sub)
_STATEMENTS = (ast.Return, ast.Assign, ast.Expr, ast.Pass)
_SAFE_BUILTINS = {"type", "set", "dict", "str", "int"}


def _guard_key(expr):
    """Key only a simple binding or constant-key dictionary access."""
    if isinstance(expr, ast.Name):
        return ("name", expr.id)
    if (isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant)
            and type(expr.slice.value) in {str, int}):
        parent = _guard_key(expr.value)
        if parent is not None:
            return ("item", parent, expr.slice.value)
    return None


def _positive_type_guard(expr):
    """A direct truthy conjunction clause proving an exact built-in type."""
    if (isinstance(expr, ast.Compare) and len(expr.ops) == 1
            and isinstance(expr.ops[0], ast.Is)
            and isinstance(expr.left, ast.Call)
            and isinstance(expr.left.func, ast.Name) and expr.left.func.id == "type"
            and len(expr.left.args) == 1 and not expr.left.keywords
            and isinstance(expr.comparators[0], ast.Name)
            and expr.comparators[0].id in {"dict", "str", "int"}):
        key = _guard_key(expr.left.args[0])
        return (key, expr.comparators[0].id) if key is not None else None
    return None


def _effectful_calls(expr):
    """A call outside the three admitted operator helpers invalidates guards."""
    for call in (n for n in ast.walk(expr) if isinstance(n, ast.Call)):
        func = call.func
        if isinstance(func, ast.Name) and func.id in {"type", "set"}:
            continue
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "re" and func.attr == "fullmatch"):
            continue
        return True
    return False


def _safe_operators(expr, known):
    """Reject operators that could dispatch to an untracked user method.

    `known` is only refined by an exact `type(value) is built-in-type`
    comparison, evaluated before later clauses of a short-circuit conjunction.
    A dict subscript is safe once its receiver has that exact type; the value
    is not presumed safe until it has its own exact type guard.
    """
    key = _guard_key(expr)
    if key is not None and key in known:
        return known[key]
    if isinstance(expr, ast.Constant):
        return type(expr.value).__name__
    if isinstance(expr, ast.Name):
        return "builtin-type" if expr.id in {"dict", "str", "int"} else "unknown"
    if isinstance(expr, ast.Attribute):
        if (isinstance(expr.value, ast.Name) and expr.value.id == "re"
                and expr.attr != "fullmatch"):
            return None
        return "unknown" if _safe_operators(expr.value, known) else None
    if isinstance(expr, ast.Subscript):
        receiver = _safe_operators(expr.value, known)
        index = _safe_operators(expr.slice, known)
        if receiver != "dict" or index not in {"str", "int"}:
            return None
        return "unknown"
    if isinstance(expr, ast.Set):
        return "set" if all(_safe_operators(e, known) in {"str", "int"}
                            for e in expr.elts) else None
    if isinstance(expr, ast.BinOp):
        left = _safe_operators(expr.left, known)
        right = _safe_operators(expr.right, known)
        if left == right == "int" and isinstance(expr.op, ast.Sub):
            return "int"
        if (left == right == "int" and isinstance(expr.op, ast.Pow)
                and isinstance(expr.right, ast.Constant)
                and type(expr.right.value) is int and expr.right.value >= 0):
            return "int"
        return None
    if isinstance(expr, ast.Call):
        if _safe_operators(expr.func, known) is None or any(
                _safe_operators(a, known) is None for a in expr.args) or any(
                _safe_operators(k.value, known) is None for k in expr.keywords):
            return None
        if isinstance(expr.func, ast.Name) and expr.func.id == "type":
            return "type" if len(expr.args) == 1 and not expr.keywords else None
        if isinstance(expr.func, ast.Name) and expr.func.id == "set":
            return "set" if len(expr.args) == 1 and not expr.keywords and _safe_operators(
                expr.args[0], known) == "dict" else None
        if (isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Name)
                and expr.func.value.id == "re" and expr.func.attr == "fullmatch"):
            return "match" if (len(expr.args) == 2 and not expr.keywords and all(
                _safe_operators(a, known) == "str" for a in expr.args)) else None
        return "unknown"
    if isinstance(expr, ast.Compare):
        values = [expr.left, *expr.comparators]
        kinds = [_safe_operators(e, known) for e in values]
        if any(kind is None for kind in kinds):
            return None
        for op, left, right in zip(expr.ops, kinds, kinds[1:]):
            if isinstance(op, (ast.Is, ast.IsNot)):
                continue
            if not isinstance(op, (ast.Eq, ast.LtE)) or left != right or left not in {
                    "str", "int", "set", "bool"}:
                return None
        return "bool"
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.And):
        # Python evaluates these clauses left to right. A guard is promoted
        # only after its direct clause is true; a nested/negated guard proves
        # nothing about the next clause.
        current = dict(known)
        for value in expr.values:
            if _safe_operators(value, current) != "bool":
                return None
            guard = _positive_type_guard(value)
            if guard:
                current[guard[0]] = guard[1]
        return "bool"
    return "unknown" if isinstance(expr, ast.Name) else None


def _docstring(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _ordinary_name(name):
    return not name.startswith("__")


def _receiver_origin(expr, globals_, locals_, method=False):
    if isinstance(expr, ast.Name):
        return (method and expr.id == "self") or expr.id in locals_ or (
            expr.id == "re" and "re" in globals_)
    if isinstance(expr, ast.Call):
        return (isinstance(expr.func, ast.Name)
                and expr.func.id in globals_ | locals_
                and not any(k.arg is None for k in expr.keywords))
    return False


def _function(fn, globals_, *, method=False):
    args = fn.args
    if (fn.decorator_list or fn.returns or args.defaults or args.kw_defaults
            or args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs
            or any(a.annotation for a in args.args)):
        return False
    params = {a.arg for a in args.args}
    if (len(params) != len(args.args) or params & (globals_ | _SAFE_BUILTINS | {"re"})
            or (method and (not args.args or args.args[0].arg != "self"))):
        return False
    local_assignments = set()
    object_locals = set()
    body = fn.body[1:] if fn.body and _docstring(fn.body[0]) else fn.body
    for stmt in body:
        if not isinstance(stmt, _STATEMENTS):
            return False
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                return False
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                if target.id in _SAFE_BUILTINS | {"re"}:
                    return False
                local_assignments.add(target.id)
                if (_receiver_origin(stmt.value, globals_, object_locals, method)
                        and isinstance(stmt.value, (ast.Call, ast.Name))):
                    object_locals.add(target.id)
                else:
                    object_locals.discard(target.id)
            elif not (method and fn.name == "__init__"
                      and isinstance(target, ast.Attribute)
                      and isinstance(target.value, ast.Name)
                      and target.value.id == "self" and _ordinary_name(target.attr)):
                return False
        parents = {id(child): parent for parent in ast.walk(stmt)
                   for child in ast.iter_child_nodes(parent)}
        for item in ast.walk(stmt):
            if not isinstance(item, _EXPRESSIONS + _STATEMENTS):
                return False
            if isinstance(item, ast.Attribute):
                if (not _ordinary_name(item.attr)
                        or (isinstance(item.ctx, ast.Load) and not
                            _receiver_origin(item.value, globals_, object_locals, method))):
                    return False
            if isinstance(item, ast.Call):
                if (not isinstance(item.func, (ast.Name, ast.Attribute))
                        or any(k.arg is None for k in item.keywords)):
                    return False
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load):
                if item.id not in params | globals_ | local_assignments | _SAFE_BUILTINS:
                    return False
                parent = parents[id(item)]
                if item.id in {"type", "set"} and not (
                        isinstance(parent, ast.Call) and parent.func is item):
                    return False
                if item.id in {"dict", "str", "int"} and not (
                        isinstance(parent, ast.Compare) and item in parent.comparators
                        and _positive_type_guard(parent) is not None):
                    return False
                if item.id == "re" and not (
                        isinstance(parent, ast.Attribute) and parent.value is item
                        and parent.attr == "fullmatch"
                        and isinstance(parents.get(id(parent)), ast.Call)
                        and parents[id(parent)].func is parent):
                    return False
        if isinstance(stmt, (ast.Return, ast.Expr, ast.Assign)) and stmt.value is not None:
            value = stmt.value
            if (_effectful_calls(value) and any(isinstance(n, (ast.BoolOp, ast.Compare,
                    ast.Subscript, ast.BinOp, ast.Set)) for n in ast.walk(value))):
                return False
            if _safe_operators(value, {}) is None:
                return False
    return not local_assignments & (params | globals_)


def certify(files, asts, *, graph=None):
    """Certify a closed explicit-import universe; never infer missing source."""
    python = [f for f in files if f["path"].endswith(".py")]
    if not python:
        return None
    if graph is None:
        # Direct certificate callers need the same graph import policy. Production
        # supplies the complete current module catalog and repository metadata.
        modules = [dict(node_id=f'{f["repository"]}:{f["path"]}:module:{module_name(f["path"])}#1',
                        kind="module", repository=f["repository"], path=f["path"],
                        qualname=module_name(f["path"])) for f in python]
        graph = Graph(modules, asts, [])
    selected = {(f["repository"], f["path"]) for f in python}
    if any(len(ids) != 1 for ids in graph.modules.values()):
        return None
    re_shadowed = {repository for repository, name in graph.modules
                   if name == "re" or name.startswith("re.")}
    for f in python:
        repo, path = f["repository"], f["path"]
        tree = asts.get(f"{repo}:{path}:module:{module_name(path)}#1")
        if not isinstance(tree, ast.Module):
            return None
        definitions = [s for s in tree.body if isinstance(s, (ast.FunctionDef, ast.ClassDef))]
        names = {s.name for s in definitions}
        if (len(names) != len(definitions) or any(not _ordinary_name(n) for n in names)
                or names & (_SAFE_BUILTINS | {"re"})):
            return None
        imported = set()
        body = tree.body[1:] if tree.body and _docstring(tree.body[0]) else tree.body
        for stmt in body:
            if isinstance(stmt, ast.ImportFrom):
                if stmt.level or not stmt.module or any(a.name == "*" for a in stmt.names):
                    return None
                if any((a.asname or a.name) == "re" for a in stmt.names):
                    return None
                allowed = graph.imported(repo, stmt.module)
                if len(allowed) != 1:
                    return None
                target_id = next(iter(allowed))
                target = graph.nodes.get(target_id)
                if (target is None or target["kind"] != "module"
                        or (target["repository"], target["path"]) not in selected):
                    return None
                target_tree = asts.get(target_id)
                if target_tree is None:
                    return None
                exports = {s.name for s in target_tree.body
                           if isinstance(s, (ast.FunctionDef, ast.ClassDef))}
                if any(a.name not in exports for a in stmt.names):
                    return None
                imported.update(a.asname or a.name for a in stmt.names)
            elif isinstance(stmt, ast.Import):
                if (len(stmt.names) != 1 or stmt.names[0].name != "re"
                        or stmt.names[0].asname is not None
                        or graph.imported(repo, "re") != {"boundary:external-or-excluded:re"}
                        or repo in re_shadowed):
                    return None
                imported.add("re")
            elif not isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
                return None
        if imported & (names | _SAFE_BUILTINS) or len(imported) != sum(
                len(s.names) for s in body if isinstance(s, (ast.ImportFrom, ast.Import))):
            return None
        globals_ = names | imported
        for item in definitions:
            if isinstance(item, ast.FunctionDef):
                if not _function(item, globals_):
                    return None
                continue
            if item.bases or item.keywords or item.decorator_list:
                return None
            class_body = item.body[1:] if item.body and _docstring(item.body[0]) else item.body
            methods = [s for s in class_body if isinstance(s, ast.FunctionDef)]
            method_names = {s.name for s in methods}
            if (len(method_names) != len(methods)
                    or any(s.name != "__init__" and not _ordinary_name(s.name)
                           for s in methods)
                    or any(not isinstance(s, (ast.FunctionDef, ast.Pass)) for s in class_body)):
                return None
            if any(not _function(s, globals_, method=True) for s in methods):
                return None
    return CERTIFICATE
