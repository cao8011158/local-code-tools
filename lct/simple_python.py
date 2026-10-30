"""Fail-closed syntax certificate for bounded Python file components."""

import ast

from .extract import module_name

CERTIFICATE = "simple-python-v2"
_EXPRESSIONS = (ast.Name, ast.Constant, ast.Call, ast.keyword, ast.Attribute,
                ast.Load, ast.Store)
_STATEMENTS = (ast.Return, ast.Assign, ast.Expr, ast.Pass)


def _docstring(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _ordinary_name(name):
    return not name.startswith("__")


def _receiver_origin(expr, globals_, locals_, method=False):
    if isinstance(expr, ast.Name):
        return (method and expr.id == "self") or expr.id in locals_
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
    if (len(params) != len(args.args) or params & globals_
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
                if item.id not in params | globals_ | local_assignments:
                    return False
    return not local_assignments & (params | globals_)


def certify(files, asts):
    """Certify a closed explicit-import universe; never infer missing source."""
    python = [f for f in files if f["path"].endswith(".py")]
    if not python or len({f["repository"] for f in python}) != 1:
        return None
    modules = {}
    for f in python:
        key = (f["repository"], module_name(f["path"]))
        if key in modules:
            return None
        modules[key] = f
    for f in python:
        repo, path = f["repository"], f["path"]
        tree = asts.get(f"{repo}:{path}:module:{module_name(path)}#1")
        if not isinstance(tree, ast.Module):
            return None
        definitions = [s for s in tree.body if isinstance(s, (ast.FunctionDef, ast.ClassDef))]
        names = {s.name for s in definitions}
        if len(names) != len(definitions) or any(not _ordinary_name(n) for n in names):
            return None
        imported = set()
        body = tree.body[1:] if tree.body and _docstring(tree.body[0]) else tree.body
        for stmt in body:
            if isinstance(stmt, ast.ImportFrom):
                if stmt.level or not stmt.module or any(a.name == "*" for a in stmt.names):
                    return None
                target = modules.get((repo, stmt.module))
                if target is None:
                    return None
                target_tree = asts.get(f"{repo}:{target['path']}:module:{stmt.module}#1")
                if target_tree is None:
                    return None
                exports = {s.name for s in target_tree.body
                           if isinstance(s, (ast.FunctionDef, ast.ClassDef))}
                if any(a.name not in exports for a in stmt.names):
                    return None
                imported.update(a.asname or a.name for a in stmt.names)
            elif not isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
                return None
        if imported & names or len(imported) != sum(
                len(s.names) for s in body if isinstance(s, ast.ImportFrom)):
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
