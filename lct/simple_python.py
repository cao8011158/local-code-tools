"""Fail-closed syntax certificate for a bounded file-component graph update.

This does not certify general Python. Every captured module must fit this subset;
otherwise the ordinary complete graph build remains authoritative.
"""

import ast

from .extract import module_name

CERTIFICATE = "simple-python-v1"
_EXPRESSIONS = (ast.Name, ast.Constant, ast.Call, ast.keyword, ast.Load, ast.Store)
_STATEMENTS = (ast.Return, ast.Assign, ast.Expr, ast.Pass)


def certify(files, asts):
    """Return a complete certificate only for a single closed import universe."""
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
        functions = {s.name for s in tree.body if isinstance(s, ast.FunctionDef)}
        imported = set()
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom):
                if stmt.level or not stmt.module or any(a.name == "*" for a in stmt.names):
                    return None
                target = modules.get((repo, stmt.module))
                if target is None:
                    return None
                target_tree = asts.get(f"{repo}:{target['path']}:module:{stmt.module}#1")
                if target_tree is None:
                    return None
                exports = {s.name for s in target_tree.body if isinstance(s, ast.FunctionDef)}
                if any(a.name not in exports for a in stmt.names):
                    return None
                imported.update(a.asname or a.name for a in stmt.names)
            elif not isinstance(stmt, ast.FunctionDef):
                return None
        if len(functions) != sum(isinstance(s, ast.FunctionDef) for s in tree.body):
            return None
        if imported & functions:
            return None
        for fn in (s for s in tree.body if isinstance(s, ast.FunctionDef)):
            args = fn.args
            if (fn.decorator_list or fn.returns or args.defaults or args.kw_defaults
                    or args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs
                    or any(a.annotation for a in args.args)):
                return None
            params = {a.arg for a in args.args}
            if len(params) != len(args.args) or params & (functions | imported):
                return None
            local_assignments = set()
            for stmt in fn.body:
                if not isinstance(stmt, _STATEMENTS):
                    return None
                if isinstance(stmt, ast.Assign):
                    if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                        return None
                    local_assignments.add(stmt.targets[0].id)
                for item in ast.walk(stmt):
                    if not isinstance(item, _EXPRESSIONS + _STATEMENTS):
                        return None
                    if isinstance(item, ast.Call):
                        if (not isinstance(item.func, ast.Name)
                                or item.func.id not in params | functions | imported
                                or any(k.arg is None for k in item.keywords)):
                            return None
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load):
                        if item.id not in params | functions | imported | local_assignments:
                            return None
            if local_assignments & (params | functions | imported):
                return None
    return CERTIFICATE
