"""Internal evidence for a narrowly certified captured dictionary flow."""

import ast
from collections import defaultdict

from .common import canonical, digest

LIMIT = 20000


def key(node):
    return isinstance(node, ast.Constant) and type(node.value) is str


def plain(stmt):
    if not isinstance(stmt, ast.FunctionDef):
        return False
    a = stmt.args
    return not (stmt.decorator_list or stmt.returns or a.posonlyargs or a.args
                or a.vararg or a.kwarg or a.kwonlyargs or a.defaults or a.kw_defaults)


def capture_shape(nodes, asts, imported):
    """Return proven origins, writes, reads and owners; reject escape/effects."""
    modules = {n["node_id"]: n for n in nodes
               if n["kind"] == "module" and n["node_id"] in asts}
    functions = defaultdict(dict)
    for n in nodes:
        if n["kind"] == "function" and n.get("parent") in modules:
            functions[n["parent"]][n["name"]] = n["node_id"]
    for module in modules:
        declarations = [s.name for s in asts[module].body if isinstance(s, ast.FunctionDef)]
        if len(set(declarations)) != len(declarations):
            return None
        for stmt in asts[module].body:
            if isinstance(stmt, ast.FunctionDef):
                functions[module].setdefault(stmt.name, stmt.name)
    origins = {}
    by_owner = defaultdict(dict)
    for module, node in modules.items():
        for stmt in asts[module].body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Dict)):
                name = stmt.targets[0].id
                if ((module, name) in origins or name in functions[module]
                        or any(not key(k) or not isinstance(v, ast.Name)
                               or v.id not in functions[module]
                               for k, v in zip(stmt.value.keys, stmt.value.values))):
                    return None
                origins[module, name] = by_owner[module][name] = dict(expr=stmt.value, writes=[
                    (k.value, stmt, v.id, k) for k, v in
                    zip(stmt.value.keys, stmt.value.values)])
    if not origins:
        return None
    reads, modeled, bindings_evidence = [], set(), []
    for (module, name), origin in origins.items():
        bindings_evidence.append((module, None, name, "declaration", origin["expr"],
                                  (module, name)))
    for module, node in modules.items():
        bindings = {name: (module, name) for name in by_owner[module]}
        imported_names = set()
        for stmt in asts[module].body:
            if not isinstance(stmt, ast.ImportFrom) or stmt.level or not stmt.module:
                continue
            possible = imported(node["repository"], stmt.module)
            if len(possible) != 1:
                continue
            target = next(iter(possible))
            if target in modules and modules[target]["repository"] == node["repository"]:
                for alias in stmt.names:
                    if (target, alias.name) in origins:
                        name = alias.asname or alias.name
                        if name in bindings or name in functions[module]:
                            return None
                        bindings[name] = (target, alias.name)
                        imported_names.add(name)
                        bindings_evidence.append((module, None, name, "import", alias,
                                                  (target, alias.name)))
        if not bindings:
            continue
        modeled.add(module)
        for stmt in asts[module].body:
            if isinstance(stmt, ast.FunctionDef):
                if not plain(stmt):
                    return None
                local = dict(bindings)
                local_alias_names = set()
                for inner in stmt.body:
                    if isinstance(inner, ast.Pass):
                        continue
                    if (isinstance(inner, ast.Assign) and len(inner.targets) == 1
                            and isinstance(inner.targets[0], ast.Name)
                            and isinstance(inner.value, ast.Name) and inner.value.id in local
                            and inner.targets[0].id not in local):
                        local[inner.targets[0].id] = local[inner.value.id]
                        bindings_evidence.append((module, stmt.name, inner.targets[0].id,
                                                  "local-alias", inner.targets[0],
                                                  local[inner.value.id]))
                        local_alias_names.add(inner.targets[0].id)
                        continue
                    call = inner.value if isinstance(inner, ast.Expr) else None
                    if (not isinstance(call, ast.Call) or call.args or call.keywords
                            or not isinstance(call.func, ast.Subscript)
                            or not isinstance(call.func.value, ast.Name)
                            or call.func.value.id not in local or not key(call.func.slice)):
                        return None
                    alias_name = call.func.value.id
                    binding = (module, stmt.name, alias_name) if alias_name in local_alias_names else (
                        module, None, alias_name)
                    reads.append((local[alias_name], module, stmt.name, call.func, binding))
            elif isinstance(stmt, ast.ImportFrom):
                if (stmt.level or not stmt.module or any(a.name == "*" for a in stmt.names)
                        or any((a.asname or a.name) not in imported_names for a in stmt.names)):
                    return None
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if (isinstance(target, ast.Name) and isinstance(stmt.value, ast.Dict)
                        and (module, target.id) in origins):
                    continue
                if (isinstance(target, ast.Name) and isinstance(stmt.value, ast.Name)
                        and stmt.value.id in bindings and target.id not in bindings
                        and target.id not in functions[module]):
                    bindings[target.id] = bindings[stmt.value.id]
                    bindings_evidence.append((module, None, target.id, "module-alias",
                                              target, bindings[stmt.value.id]))
                    continue
                if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                        and target.value.id in bindings and key(target.slice)
                        and isinstance(stmt.value, ast.Name)
                        and stmt.value.id in functions[module]
                        and bindings[target.value.id][0] == module):
                    origins[bindings[target.value.id]]["writes"].append(
                        (target.slice.value, stmt, stmt.value.id, target.slice))
                    continue
                return None
            elif (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                  and isinstance(stmt.value.value, str)):
                continue
            else:
                return None
    return (origins, reads, modeled, functions, bindings_evidence) if reads else None


def evidence(nodes, asts, analyzer, sites, imported):
    """Persist only actual analyzer reads agreeing with proved source support."""
    result = dict(nodes=[], edges=[], reads=[], complete=False)
    shape = capture_shape(nodes, asts, imported)
    if shape is None:
        result["complete"] = True  # only the independent syntax certificate can admit it
        return result
    origins, reads, _, functions, bindings_evidence = shape
    byid = {n["node_id"]: n for n in nodes}
    sites_at = {(s["execution_owner"], s["line"], s["column"]): s for s in sites}
    entries, containers, latest, entry_nodes, binding_ids = {}, {}, {}, {}, {}
    def bounded():
        return len(result["nodes"]) + len(result["edges"]) + len(result["reads"]) <= LIMIT - 10
    def ident(module, kind, *parts):
        node = byid[module]
        return "value:" + digest(canonical([node["repository"], node["path"],
                                            kind, *parts]))
    def entry_for(module, name, value):
        address = module, name, value
        if address not in entries:
            container = containers[module, name]
            entry = ident(module, "entry", container, value)
            entries[address] = entry
            record = dict(id=entry, module=module, kind="entry",
                          container=container, key=value, present=False)
            entry_nodes[entry] = record
            result["nodes"].append(record)
            result["edges"].append(dict(source=container, target=entry, kind="ADDRESSES"))
        return entries[address]
    for (module, name), origin in origins.items():
        if not bounded():
            return dict(nodes=[], edges=[], reads=[], complete=False)
        expr = origin["expr"]
        container = ident(module, "container", expr.lineno, expr.col_offset, name)
        containers[module, name] = container
        result["nodes"].append(dict(id=container, kind="container", module=module,
                                    name=name, line=expr.lineno, column=expr.col_offset))
    for module, function, name, kind, source, origin in bindings_evidence:
        if not bounded():
            return dict(nodes=[], edges=[], reads=[], complete=False)
        binding = ident(module, "binding", function, name, kind,
                        source.lineno, source.col_offset)
        binding_ids[module, function, name] = binding
        result["nodes"].append(dict(id=binding, kind="binding", module=module,
                                    name=name, binding_kind=kind, owner_function=function,
                                    line=source.lineno, column=source.col_offset))
        result["edges"].append(dict(source=binding,
                                    target=containers[origin], kind="BINDS"))
    for (module, name), origin in origins.items():
        for value, stmt, target, key_node in origin["writes"]:
            if not bounded():
                return dict(nodes=[], edges=[], reads=[], complete=False)
            entry = entry_for(module, name, value)
            write = ident(module, "write", stmt.lineno, stmt.col_offset, key_node.col_offset)
            target_id = functions[module][target]
            result["nodes"].append(dict(id=write, kind="write", module=module,
                                        line=stmt.lineno, column=stmt.col_offset, target=target_id))
            result["edges"].extend((dict(source=write, target=entry, kind="WRITES"),
                                    dict(source=write, target=target_id, kind="VALUE")))
            latest[module, name, value] = write, target_id
    for address in latest:
        entry = entries[address]
        entry_nodes[entry]["present"] = True
    for (module, name), consumer, function, expr, binding_key in reads:
        if not bounded():
            return dict(nodes=[], edges=[], reads=[], complete=False)
        value = expr.slice.value
        entry = entry_for(module, name, value)
        site = sites_at.get((functions[consumer].get(function), expr.lineno, expr.col_offset))
        witness = (analyzer.value_reads.get((site["execution_owner"], expr.lineno,
                                            expr.col_offset)) if site else None)
        expected = {latest[module, name, value][1]} if (module, name, value) in latest else set()
        actual = {a.target for a in witness.atoms if a.kind == "callable"} if witness else set()
        if (site is None or witness is None or witness.reasons or actual != expected
                or set(site["targets"]) != expected or site["unknown_origin"]):
            return result
        read = ident(consumer, "read", expr.lineno, expr.col_offset, value)
        result["nodes"].append(dict(id=read, kind="read", module=consumer,
                                    site_id=site["site_id"], line=expr.lineno,
                                    column=expr.col_offset, targets=sorted(actual), unknown=False))
        result["edges"].append(dict(source=read, target=entry, kind="READS"))
        if binding_key not in binding_ids:
            return dict(nodes=[], edges=[], reads=[], complete=False)
        result["edges"].append(dict(source=read, target=binding_ids[binding_key],
                                    kind="USES_BINDING"))
        for target in expected:
            result["edges"].append(dict(source=read, target=target, kind="POSSIBLE_CALLS"))
        if (module, name, value) in latest:
            result["edges"].append(dict(source=latest[module, name, value][0],
                                        target=read, kind="REACHES"))
        result["reads"].append(dict(entry=entry, read=read,
            consumer_repository=byid[consumer]["repository"],
            consumer_path=byid[consumer]["path"]))
    result["complete"] = (len(result["nodes"]) + len(result["edges"]) +
                          len(result["reads"]) <= LIMIT)
    return result
