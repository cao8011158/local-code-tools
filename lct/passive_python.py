"""Source-only proof for inert literal-return functions."""

import ast

from .extract import module_name
from .simple_python import CERTIFICATE, _certify_v4

POLICY = "literal-functions-v1"


def certify(file, tree):
    """Prove a strict-v6 literal-function module or reject its source."""
    if not isinstance(tree, ast.Module):
        return None
    body = tree.body[1:] if ast.get_docstring(tree) else tree.body
    names = set()
    for stmt in body:
        if not isinstance(stmt, ast.FunctionDef) or stmt.name.startswith("__") or stmt.name in names:
            return None
        names.add(stmt.name)
        args = stmt.args
        if (stmt.decorator_list or stmt.returns or getattr(stmt, "type_params", ()) or
                args.posonlyargs or args.kwonlyargs or args.defaults or args.kw_defaults or
                args.vararg or args.kwarg or any(a.annotation for a in args.args)):
            return None
        inner = stmt.body[1:] if ast.get_docstring(stmt) else stmt.body
        if any(not (isinstance(s, ast.Pass) or isinstance(s, ast.Return) and
                    (s.value is None or isinstance(s.value, ast.Constant) and
                     type(s.value.value) in {str, int, float, bool, bytes, type(None)}))
               for s in inner):
            return None
    module = f"{file['repository']}:{file['path']}:module:{module_name(file['path'])}#1"
    if _certify_v4([file], {module: tree}) != CERTIFICATE:
        return None
    return dict(repository=file["repository"], path=file["path"], sha256=file["sha256"],
                policy=POLICY)
