"""Fail-closed syntax certificate for bounded Python file components."""

import ast

from .extract import module_name
from .graph import Graph

CERTIFICATE = "simple-python-v6"
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
    if (getattr(fn, "type_params", ()) or fn.decorator_list or fn.returns or args.defaults or args.kw_defaults
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


_COMMON_RESERVED = {"str", "int", "float", "bool", "bytes", "None", "Exception",
                    "property", "super", "dataclass", "re"} | _SAFE_BUILTINS


def _annotation(node):
    return node is None or (isinstance(node, ast.Constant) and node.value is None) or (
        isinstance(node, ast.Name) and node.id in {"str", "int", "float", "bool", "bytes"})


def _field(node, roots):
    if isinstance(node, ast.Name):
        return node.id in roots
    return isinstance(node, ast.Attribute) and _ordinary_name(node.attr) and _field(node.value, roots)


def _common_function(fn, globals_, constructors, *, method=False, exception=False, prop=False):
    args = fn.args
    if (getattr(fn, "type_params", ()) or args.posonlyargs or args.vararg or args.kwarg or args.defaults
            or any(d is not None and (not isinstance(d, ast.Constant) or
                    type(d.value) not in {str, int, float, bool, bytes, type(None)})
                   for d in args.kw_defaults)
            or any(not _annotation(a.annotation) for a in args.args + args.kwonlyargs)
            or not _annotation(fn.returns)):
        return False
    if prop:
        if (len(fn.decorator_list) != 1 or not isinstance(fn.decorator_list[0], ast.Name)
                or fn.decorator_list[0].id != "property" or len(args.args) != 1
                or args.args[0].arg != "self" or args.kwonlyargs):
            return False
    elif fn.decorator_list:
        return False
    params = [a.arg for a in args.args + args.kwonlyargs]
    if (len(params) != len(set(params)) or set(params) & (globals_ | _COMMON_RESERVED)
            or method and (not args.args or args.args[0].arg != "self")):
        return False
    body = fn.body[1:] if fn.body and _docstring(fn.body[0]) else fn.body
    if prop:
        return len(body) == 1 and isinstance(body[0], ast.Return) and _field(
            body[0].value, {"self"}) and isinstance(body[0].value, ast.Attribute)
    locals_, objects = set(), set()

    def expr(node):
        if isinstance(node, ast.Constant):
            return type(node.value) in {str, int, float, bool, bytes, type(None)}
        if isinstance(node, ast.Name):
            return (node.id == "self" and method or
                    node.id in set(params) | locals_ | globals_ and node.id not in _COMMON_RESERVED)
        if isinstance(node, ast.Attribute):
            return _field(node, objects | ({"self"} if method else set()))
        if isinstance(node, ast.Call):
            func = node.func
            super_init = (exception and fn.name == "__init__" and
                          isinstance(func, ast.Attribute) and func.attr == "__init__" and
                          isinstance(func.value, ast.Call) and
                          isinstance(func.value.func, ast.Name) and
                          func.value.func.id == "super" and not func.value.args and
                          not func.value.keywords)
            if not super_init and not (
                    isinstance(func, ast.Name) and func.id in globals_ | locals_ | set(params)
                    and func.id not in _COMMON_RESERVED or
                    isinstance(func, ast.Attribute) and expr(func)):
                return False
            return all(expr(a) for a in node.args) and all(
                k.arg is not None and expr(k.value) for k in node.keywords)
        return False

    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, (ast.Return, ast.Expr)):
            if not expr(stmt.value):
                return False
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and expr(stmt.value):
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                if target.id in set(params) | globals_ | _COMMON_RESERVED:
                    return False
                locals_.add(target.id)
                if (isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)
                        and stmt.value.func.id in constructors or
                        isinstance(stmt.value, ast.Name) and stmt.value.id in objects):
                    objects.add(target.id)
                else:
                    objects.discard(target.id)
            elif not (method and fn.name == "__init__" and isinstance(target, ast.Attribute)
                      and isinstance(target.value, ast.Name) and target.value.id == "self"
                      and _ordinary_name(target.attr)):
                return False
        else:
            return False
    return True


def _common_class(cls, globals_, constructors, dataclass_import):
    body = cls.body[1:] if cls.body and _docstring(cls.body[0]) else cls.body
    if getattr(cls, "type_params", ()) or cls.keywords:
        return False
    if cls.decorator_list:
        if not dataclass_import or cls.bases or len(cls.decorator_list) != 1:
            return False
        decorator = cls.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name)
                or decorator.func.id != "dataclass" or decorator.args
                or len(decorator.keywords) != 2 or
                any(not isinstance(k.value, ast.Constant) or type(k.value.value) is not bool
                    for k in decorator.keywords) or
                {(k.arg, k.value.value) for k in decorator.keywords}
                != {("frozen", True), ("slots", True)}):
            return False
        fields = [s.target.id for s in body if isinstance(s, ast.AnnAssign)
                  and isinstance(s.target, ast.Name) and s.simple and s.value is None
                  and _annotation(s.annotation)]
        return len(fields) == len(set(fields)) == len(body) and all(
            _ordinary_name(f) and f not in _COMMON_RESERVED for f in fields)
    exception = len(cls.bases) == 1 and isinstance(cls.bases[0], ast.Name) and cls.bases[0].id == "Exception"
    if cls.bases and not exception:
        return False
    methods = [s for s in body if isinstance(s, ast.FunctionDef)]
    names = [s.name for s in methods]
    return (len(names) == len(set(names)) and not set(names) & _COMMON_RESERVED
            and all(isinstance(s, (ast.FunctionDef, ast.Pass)) for s in body)
            and all(n == "__init__" or _ordinary_name(n) for n in names)
            and all(_common_function(s, globals_, constructors, method=True,
                                     exception=exception, prop=bool(s.decorator_list))
                    for s in methods))


def _certify_common(files, asts, graph, selected, *, _context=None):
    context = _context if _context is not None else _certificate_context(graph)
    for f in files:
        repo, path = f["repository"], f["path"]
        module = f"{repo}:{path}:module:{module_name(path)}#1"
        tree = asts.get(module)
        if not isinstance(tree, ast.Module):
            return False
        body = tree.body[1:] if tree.body and _docstring(tree.body[0]) else tree.body
        definitions = [s for s in body if isinstance(s, (ast.FunctionDef, ast.ClassDef))]
        names = [s.name for s in definitions]
        if (len(names) != len(set(names)) or
                any(not _ordinary_name(name) for name in names) or
                set(names) & _COMMON_RESERVED):
            return False
        imported, dataclass_import = set(), False
        for stmt in body:
            if isinstance(stmt, ast.ImportFrom):
                if not stmt.module or any(a.name == "*" for a in stmt.names):
                    return False
                request = graph.import_request_module(module, stmt, stmt.names[0])
                if request is None:
                    return False
                targets = graph.imported(repo, request)
                if (stmt.level == 0 and request == "dataclasses" and len(stmt.names) == 1 and
                        stmt.names[0].name == "dataclass" and stmt.names[0].asname is None and
                        targets == {"boundary:external-or-excluded:dataclasses"} and
                        repo not in context["dataclasses_shadowed"]):
                    imported.add("dataclass")
                    dataclass_import = True
                    continue
                if len(targets) != 1:
                    return False
                target = next(iter(targets))
                if (target not in graph.nodes or
                        (graph.nodes[target]["repository"], graph.nodes[target]["path"]) not in selected or
                        target not in asts):
                    return False
                exports = {s.name for s in asts[target].body
                           if isinstance(s, (ast.FunctionDef, ast.ClassDef))}
                if any(a.name not in exports for a in stmt.names):
                    return False
                imported.update(a.asname or a.name for a in stmt.names)
            elif not isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
                return False
        if (len(imported) != sum(len(s.names) for s in body if isinstance(s, ast.ImportFrom))
                or set(names) & imported or (imported - {"dataclass"}) & _COMMON_RESERVED):
            return False
        globals_ = set(names) | (imported - {"dataclass"})
        constructors = {s.name for s in definitions if isinstance(s, ast.ClassDef)}
        if any(not (_common_function(s, globals_, constructors) if isinstance(s, ast.FunctionDef)
                    else _common_class(s, globals_, constructors, dataclass_import))
               for s in definitions):
            return False
    return True


def _certificate_context(graph):
    return dict(ambiguous=any(len(ids) != 1 for ids in graph.modules.values()),
                re_shadowed={repo for repo, name in graph.modules
                             if name == "re" or name.startswith("re.")},
                dataclasses_shadowed={repo for repo, name in graph.modules
                                      if name == "dataclasses" or name.startswith("dataclasses.")})


def _certify_v4(files, asts, *, graph=None, selected_context=None, _context=None):
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
    # A mixed v5 capture can validate modeled dictionary modules separately,
    # then let plain modules import their definitions. The default remains the
    # original self-contained v4 selection for every other caller.
    selected = (selected_context if selected_context is not None else
                {(f["repository"], f["path"]) for f in python})
    context = _context if _context is not None else _certificate_context(graph)
    if context["ambiguous"]:
        return None
    re_shadowed = context["re_shadowed"]
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
                if not stmt.module or any(a.name == "*" for a in stmt.names):
                    return None
                if any((a.asname or a.name) == "re" for a in stmt.names):
                    return None
                request = graph.import_request_module(
                    f"{repo}:{path}:module:{module_name(path)}#1", stmt, stmt.names[0])
                if request is None:
                    return None
                allowed = graph.imported(repo, request)
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
            if getattr(item, "type_params", ()) or item.bases or item.keywords or item.decorator_list:
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


def certify(files, asts, *, graph=None):
    """Classify bounded syntax for legacy source metadata only."""
    python = [f for f in files if f["path"].endswith(".py")]
    if not python:
        return None
    if graph is None:
        # Preserve direct callers' original synthetic graph and strict policy.
        return _certify_v4(files, asts)
    context = _certificate_context(graph)
    if context["ambiguous"]:
        return None
    if _certify_v4(files, asts, graph=graph, _context=context) == CERTIFICATE:
        return CERTIFICATE
    selected = {(f["repository"], f["path"]) for f in python}
    def plain_ok(items):
        return all((_certify_v4([f], asts, graph=graph, selected_context=selected,
                                _context=context) == CERTIFICATE or
                    _certify_common([f], asts, graph, selected, _context=context))
                   for f in items)
    if plain_ok(python):
        return CERTIFICATE
    # The former dictionary admission certificate inferred function values
    # from literal writes. Source dependency recording is independent of it.
    return None
