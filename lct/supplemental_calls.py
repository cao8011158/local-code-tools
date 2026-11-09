"""Narrow source association for a final Jedi call observation with no names.

Callable identities are mapped Jedi results. Existing source facts associate an
exact container entry or a known formal with the actual source expression.
"""

import ast
from collections import defaultdict
from pathlib import Path

from .python_analysis import CALLABLE_KINDS


class PriorSourceIndex:
    """Build each old-sidecar source index only if a relevant miss needs it."""

    def __init__(self, records, unchanged):
        self.records = records
        self.unchanged = unchanged
        self._supports = None
        self._writes = None

    def supports(self, owner):
        if self._supports is None:
            rows = defaultdict(list)
            for row in self.records[0]:
                if row['kind'] == 'actual-parameter':
                    rows[row['consumer_owner']].append(row)
            self._supports = rows
        return self._supports.get(owner, ())

    def writes(self, origin):
        if self._writes is None:
            rows = defaultdict(list)
            for row in self.records[2]:
                rows[row['origin']].append(row)
            self._writes = rows
        return self._writes.get(origin, ())


class SupplementalCalls:
    def __init__(self, analyzer, prior=None, selected=None):
        self.a = analyzer
        self.r = analyzer.recorder
        self.prior = prior
        self.selected = selected or set()
        self.writes = defaultdict(list)
        self.exact_writes = defaultdict(list)
        self.range_writes = defaultdict(list)
        self._current_writes_indexed = False
        self._loaded_origins = set()
        self._loaded_formals = set()
        self._uncertain_formals = set()
        self._source_cache = {}
        self._site_index = None
        self._registrations_cache = {}
        self._origin_safety = {}
        self.attempts = self.proven = self.source_queries = self.metadata_queries = 0

    def _append_write(self, row):
        self.writes[row['origin']].append(row)
        if row['key_kind'] == 'exact':
            self.exact_writes[row['origin'], row['key']].append(row)
        else:
            self.range_writes[row['origin']].append(row)

    def _load_current_writes(self):
        if not self._current_writes_indexed:
            for row in self.r.writes.values():
                self._append_write(row)
            self._current_writes_indexed = True

    def _load_formals(self, owner):
        if owner in self._loaded_formals or self.prior is None:
            return
        self._loaded_formals.add(owner)
        for row in self.prior.supports(owner):
            if (row['producer_owner'] not in self.prior.unchanged or
                    owner not in self.prior.unchanged or
                    row['producer_owner'] in self.selected):
                continue
            key = owner, row['detail']['parameter']
            if row['status'] != 'observed' or row['detail'].get('source_uncertain'):
                self._uncertain_formals.add(key)
                continue
            source = self._source_at(row['producer_owner'], row['producer_location'])
            call = self._call_at(row['producer_owner'], row['detail'].get('call_location'))
            if source is None or call is None:
                self._uncertain_formals.add(key)
                continue
            values = self.r.actual_values[key]
            if not any(record[2] == call['site_id'] and
                       record[1].lineno == source.lineno and
                       record[1].col_offset == source.col_offset for record in values):
                values.append((row['producer_owner'], source, call['site_id'], False))

    def _load_origin(self, origin):
        if origin in self._loaded_origins or self.prior is None:
            return
        self._loaded_origins.add(origin)
        for row in self.prior.writes(origin):
            if (row['producer_owner'] not in self.prior.unchanged or
                    row['producer_owner'] in self.selected):
                continue
            found = self._source_at(row['producer_owner'], row['producer_location'])
            if not isinstance(found, ast.Subscript):
                # An untranslatable prior write cannot certify an exact value.
                self._append_write(row)
                continue
            updated = dict(row, producer_site=self.r.site(
                row['producer_owner'], found, 'write'))
            if not any(existing['producer_site'] == updated['producer_site']
                       for existing in self.writes[origin]):
                self._append_write(updated)

    def _source_at(self, owner, location):
        if owner not in self.a.trees or location is None:
            return None
        if owner not in self._source_cache:
            index = defaultdict(list)
            for node in ast.walk(self.a.trees[owner]):
                if isinstance(node, ast.expr):
                    index[(node.lineno, node.col_offset, node.end_lineno,
                           node.end_col_offset)].append(node)
            self._source_cache[owner] = index
        candidates = self._source_cache[owner].get((location['line'], location['column'],
            location['end_line'], location['end_column']), ())
        return next((node for node in candidates if ast.unparse(node)[:240] ==
                     location['expression']), None)

    def _call_at(self, owner, location):
        if location is None:
            return None
        self._ensure_site_index()
        site = self._site_index.get((owner, location['line'], location['column'],
                                     location['end_line'], location['end_column']))
        return site if site and site['expression'] == location['expression'] else None

    def _ensure_site_index(self):
        if self._site_index is None:
            self._site_index = {(site['execution_owner'], site['line'], site['column'],
                                 site['end_line'], site['end_column']): site
                                for site in self.a.sites if site['kind'] == 'call'}
            self._site_by_id = {site['site_id']: site for site in self._site_index.values()}

    def _infer(self, owner, expr):
        self.source_queries += 1
        result = self.a.query(owner, expr)
        if result.reasons or not result.atoms or any(
                a.kind not in CALLABLE_KINDS for a in result.atoms):
            return set()
        return {a.target for a in result.atoms}

    def _write(self, row):
        owner = row['producer_owner']
        tree = self.a.trees[owner]
        for stmt in tree.body:
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
                continue
            targets = stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,)
            for target in targets:
                if isinstance(target, ast.Subscript) and self.r.site(owner, target, 'write') == row['producer_site']:
                    return owner, stmt, target, stmt.value
        return None

    def _unconditional(self, callsite):
        owner = callsite['execution_owner']
        tree = self.a.trees[owner]
        return any(isinstance(stmt, ast.Expr) and stmt.value is callsite['_call']
                   for stmt in tree.body)

    def _registered(self, writer, key_param, value_param, desired_key):
        self._load_formals(writer)
        if ((writer, key_param) in self._uncertain_formals or
                (writer, value_param) in self._uncertain_formals):
            return None
        cache_key = writer, key_param, value_param
        if cache_key not in self._registrations_cache:
            self._registrations_cache[cache_key] = self._registration_groups(
                writer, key_param, value_param)
        groups = self._registrations_cache[cache_key]
        return None if groups is None else groups.get(desired_key, [])

    def _registration_groups(self, writer, key_param, value_param):
        keys = defaultdict(list)
        for owner, expr, site, uncertain in self.r.actual_values.get((writer, key_param), ()):
            keys[site].append((owner, expr, uncertain))
        values = defaultdict(list)
        for owner, expr, site, uncertain in self.r.actual_values.get((writer, value_param), ()):
            values[site].append((owner, expr, uncertain))
        groups = defaultdict(list)
        self._ensure_site_index()
        sites = self._site_by_id
        for site, key_sources in keys.items():
            callsite = sites.get(site)
            if callsite is None or not self._unconditional(callsite):
                # Conditional or otherwise unproved writes may reach this key.
                return None
            if len(key_sources) != 1 or len(values.get(site, ())) != 1:
                return None
            owner, key_expr, key_uncertain = key_sources[0]
            value_owner, value_expr, value_uncertain = values[site][0]
            if key_uncertain or value_uncertain or owner != value_owner:
                return None
            kind, key = self.r.key(key_expr)
            if kind != 'exact':
                return None
            groups[key].append((value_owner, value_expr, site))
        return groups

    def _safe_origin(self, origin):
        cached = self._origin_safety.get(origin)
        if cached is not None:
            return cached
        self._origin_safety[origin] = False
        # Only a captured literal allocation is admitted. Every recorded
        # write to it must have a source association or the result is unknown.
        allocation = origin.rsplit(':', 2)
        if len(allocation) != 3 or allocation[0] not in self.a.trees:
            return False
        if not any(isinstance(stmt, (ast.Assign, ast.AnnAssign)) and
                   isinstance(stmt.value, ast.Dict) and
                   f'{allocation[0]}:{stmt.value.lineno}:{stmt.value.col_offset}' == origin
                   for stmt in self.a.trees[allocation[0]].body):
            return False
        allocation_tree = self.a.trees[allocation[0]]
        allocation_names = {
            t.id for stmt in allocation_tree.body
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and
            isinstance(stmt.value, ast.Dict) and
            f'{allocation[0]}:{stmt.value.lineno}:{stmt.value.col_offset}' == origin
            for t in (stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,))
            if isinstance(t, ast.Name)}
        if not allocation_names:
            return False
        alias_names = set(allocation_names)
        for statement in allocation_tree.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
                for target in targets:
                    if isinstance(target, ast.Name) and origin in self.r.origins_for(
                            (allocation[0], target.id))[0]:
                        alias_names.add(target.id)
        # This bounded association admits only a stable module binding and
        # explicitly recorded writes. Rebinding or an unmodelled mutation
        # invalidates that proof instead of invoking a control-flow solver.
        for stmt in allocation_tree.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,)
                if any(isinstance(t, ast.Name) and t.id in alias_names for t in targets):
                    original_allocation = (isinstance(stmt.value, ast.Dict) and
                        f'{allocation[0]}:{stmt.value.lineno}:{stmt.value.col_offset}' == origin)
                    alias_copy = (isinstance(stmt.value, ast.Name) and
                                  stmt.value.id in alias_names)
                    if not original_allocation and not alias_copy:
                        return False
            if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and
                    isinstance(stmt.value.func, ast.Attribute) and
                    isinstance(stmt.value.func.value, ast.Name) and
                    stmt.value.func.value.id in alias_names):
                return False
        if any(isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Attribute) and
                isinstance(node.func.value, ast.Name) and
                node.func.value.id in alias_names or
                any(isinstance(arg, ast.Name) and arg.id in alias_names
                    for arg in node.args))
               for node in ast.walk(allocation_tree)):
            return False
        self._origin_safety[origin] = True
        return True

    def container(self, item):
        call, owner = item['_call'], item['execution_owner']
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Subscript):
            return set(), []
        kind, key = self.r.key(call.func.slice)
        origins = self.r.receiver_origins(owner, call.func.value)
        if kind != 'exact' or len(origins) != 1:
            return set(), []
        origin = next(iter(origins))
        self._load_current_writes()
        self._load_origin(origin)
        if not self._safe_origin(origin):
            return set(), []
        source_values = []
        for row in (*self.exact_writes.get((origin, key), ()),
                    *self.range_writes.get(origin, ())):
            write = self._write(row)
            if write is None or row['kind'] != 'subscript-write':
                return set(), []
            writer, _, target, value = write
            if row['key_kind'] == 'exact' and not isinstance(self.a.trees[writer], ast.Module):
                return set(), []
            if isinstance(target.ctx, ast.Del):
                return set(), []
            if row['key_kind'] == 'exact':
                source_values.append((writer, value, row['producer_site']))
            elif (isinstance(self.a.trees[writer], (ast.FunctionDef, ast.AsyncFunctionDef))
                  and isinstance(target.slice, ast.Name) and isinstance(value, ast.Name)):
                tree = self.a.trees[writer]
                if any(isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
                       and n.id in {target.slice.id, value.id}
                       for statement in tree.body if statement is not write[1]
                       for n in ast.walk(statement)):
                    return set(), []
                registrations = self._registered(writer, target.slice.id, value.id, key)
                if registrations is None:
                    return set(), []
                source_values.extend(registrations)
            else:
                return set(), []
        if len(source_values) != 1:
            return set(), []
        producer, expr, source_site = source_values[0]
        targets = self._infer(producer, expr)
        if len(targets) != 1:
            return set(), []
        return targets, [(producer, expr, source_site)]

    def definition_parameters(self, target, source=None):
        """Ask Jedi for signature metadata at its already mapped declaration."""
        tree = self.a.trees[target]
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        module = self.a.module_for[target]
        col = len(self.a._source_lines[module][tree.lineno - 1].encode('utf-8')[:
            tree.col_offset + len(('async def ' if isinstance(tree, ast.AsyncFunctionDef) else 'def ').encode())
            + len(tree.name.encode())].decode('utf-8'))
        try:
            names = ()
            if source is not None:
                producer, expr, _ = source
                key = (self.a.module_for[producer], expr.end_lineno,
                       expr.end_col_offset, False)
                observed = self.a._raw_jedi_observations.get(key)
                if observed and not observed[1]:
                    names = observed[0]
            if not names:
                self.metadata_queries += 1
                names = self.a.scripts[module].infer(tree.lineno, col)
            for name in names:
                mapped, _ = self.a.map_name(name)
                if {a.target for a in mapped.atoms} != {target}:
                    continue
                for signature in name.get_signatures():
                    parameters = []
                    for p in signature.params:
                        path = self.a.paths.get(Path(p.module_path).resolve()) if p.module_path else None
                        stable = (self.a.nodes[path]['repository'] + '/' + self.a.nodes[path]['path']
                                  if path is not None else None)
                        parameters.append(dict(name=p.name, kind=str(p.kind), line=p.line,
                                               column=p.column, module_path=stable))
                    return parameters
        except Exception:
            return []
        return []

    def callback(self, item):
        owner, expr = item['execution_owner'], item['_expr']
        tree = self.a.trees[owner]
        if not isinstance(expr, ast.Name) or not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return set(), []
        if expr.id not in {arg.arg for arg in tree.args.posonlyargs + tree.args.args +
                           tree.args.kwonlyargs}:
            return set(), []
        self._load_formals(owner)
        if (owner, expr.id) in self._uncertain_formals or not self.r.actual_values.get((owner, expr.id)):
            return set(), []
        if any(isinstance(node, ast.Name) and node.id == expr.id and
               isinstance(node.ctx, (ast.Store, ast.Del))
               for statement in tree.body for node in ast.walk(statement)):
            return set(), []
        values = self.r.actual_values.get((owner, expr.id), ())
        if len(values) != 1 or values[0][3]:
            return set(), []
        producer, actual, source_site, _ = values[0]
        targets = self._infer(producer, actual)
        return (targets, [(producer, actual, source_site)]) if len(targets) == 1 else (set(), [])

    def support(self, item, sources, targets):
        consumer = item['execution_owner']
        for producer, source, source_site in sources:
            self.r.support(producer, source, consumer, item['_expr'], 'supplemental-call-source',
                           dict(target_id=next(iter(targets)), call_site=item['site_id']),
                           'observed',
                           consumer_site=item['site_id'])
