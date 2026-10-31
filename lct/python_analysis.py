"""Captured-source Jedi bridge with finite lexical/callback/container associations.

No analyzed module is imported. This is not a Python executor or iterative type
engine: unsupported mutation and control flow contribute explicit unknown origins.
"""

import ast
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import jedi

from .common import canonical, digest
from .dependency_origins import LIMIT as ORIGIN_LIMIT, key_identity
from .analysis_inputs import AnalysisInputs
from .parso_cache_compat import ensure_parso_cache_timestamps
from .python_access import AccessKind, ReceiverAccess, access, combine
from .python_effects import (
    EffectCatalog,
    EffectCoverage,
    EffectKind,
    EffectOutcome,
    implicit_execution_effect,
    valid_coverage,
)

_DYNAMIC = object()
_SAME_INPUT_SCOPE = object()


class RequiredAnalysisContext(Exception):
    """A captured Jedi target needs its AST in the bounded compute component."""

    def __init__(self, repository, path):
        self.repository, self.path = repository, path
        super().__init__(repository, path)
ANALYSIS_DEPENDENCY_LIMIT = 20000
ANALYSIS_READ_KINDS = frozenset({"container-effects", "member-lookup", "return-body",
                                 "parameter-origin", "jedi-target"})
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
    """Known alternatives, unknown origins and transitive effect obligations are separate."""

    atoms: frozenset = frozenset()
    reasons: frozenset = frozenset()
    proofs: frozenset = frozenset()
    requirements: frozenset = frozenset()

    @property
    def unknown(self):
        return bool(self.reasons)


def union(*results):
    """Combine alternatives without losing unknown contributions."""
    return Result(
        frozenset(a for r in results for a in r.atoms),
        frozenset(x for r in results for x in r.reasons),
        frozenset(p for r in results for p in r.proofs),
        frozenset(p for r in results for p in r.requirements),
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
    """Attach a rule label only; separate coverage checks govern effect completeness."""
    return Result(
        result.atoms, result.reasons, result.proofs | frozenset([rule]), result.requirements
    )


def invalid(rule):
    """Prove that an attempted call has no valid target in supported syntax."""
    return Result(proofs=frozenset([rule]))


class Analyzer:
    """Resolve one private source capture with recursion and work budgets."""

    def __init__(self, nodes, trees, repos, imported, query_reuse=None,
                 candidate_components=None, source_context=None,
                 candidate_site_evidence=None, selected_owners=None):
        ensure_parso_cache_timestamps()
        self.nodes, self.trees, self.repos = nodes, trees, repos
        self.imported = imported
        self.candidate_components = candidate_components
        self.analysis_inputs = AnalysisInputs({i: n for i, n in nodes.items()
                                              if n["kind"] == "module"})
        self._analysis_input_ready = False
        self.owner = {id(t): ident for ident, t in trees.items()}
        self.modules = {i: t for i, t in trees.items() if isinstance(t, ast.Module)}
        self.statements = {
            i: t.body if not isinstance(t, ast.Lambda) else [] for i, t in trees.items()
        }
        self.queries, self.memo, self.container_exprs = {}, {}, {}
        self._query_context = {}
        self.query_reuse = query_reuse or {}
        self.reused_queries = 0
        self.executed_queries = 0
        self._query_inflight = 0
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
        self.coverage_models = {}
        self.method_effects = {}
        self.execution_nodes = {}
        context = (source_context if source_context is not None else
                   {ident: tree._lct_source for ident, tree in self.modules.items()})
        for ident, source in context.items():
            if ident not in nodes or nodes[ident]["kind"] != "module":
                raise ValueError("Captured context module unavailable")
            n = nodes[ident]
            path = self.root / n["repository"] / n["path"]
            if not path.resolve().is_relative_to(self.root):
                raise ValueError("Source path escapes captured workspace")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            self.paths[path.resolve()] = ident
        roots = defaultdict(set)
        for path, ident in self.paths.items():
            module = nodes[ident]
            mod = module["qualname"]
            depth = len(mod.split(".")) if path.name == "__init__.py" else len(mod.split(".")) - 1
            root = path.parent
            for _ in range(depth):
                root = root.parent
            roots[module["repository"]].add(str(root))
        library_paths = [
            p
            for p in sys.path
            if p
            and ("site-packages" in p or "python" in p.lower())
            and str(Path(p).resolve()) != str(Path.cwd().resolve())
        ]
        projects = {}
        for repository in roots:
            dependencies = set()
            for ident in context:
                module = nodes[ident]
                if module["repository"] == repository:
                    continue
                if ident in self.imported(repository, module["qualname"]):
                    dependencies.update(roots[module["repository"]])
            projects[repository] = jedi.Project(
                self.root / repository,
                sys_path=sorted(roots[repository]) + sorted(dependencies - roots[repository])
                + library_paths,
                smart_sys_path=False,
                load_unsafe_extensions=False,
            )
        for path, ident in self.paths.items():
            if ident not in self.modules:
                continue
            self.scripts[ident] = jedi.Script(
                code=trees[ident]._lct_source, path=path,
                project=projects[nodes[ident]["repository"]],
            )
        for ident in trees:
            mod = ident
            while nodes[mod]["kind"] != "module":
                mod = nodes[mod]["parent"]
            self.module_for[ident] = mod
        self.analysis_reads = set()
        self.analysis_watches = set()
        self.unit_analysis_reads = set()
        self.unit_analysis_watches = set()
        self.unit_input_events = set()
        self._unit_component_members = {}
        self.unit_supports = {}
        self.unit_container_subscriptions = {}
        self.unit_container_writes = {}
        self._unit_writes_by_origin = defaultdict(list)
        self._unit_subscriptions_by_query = defaultdict(dict)
        self.unit_dependency_truncated = False
        self.analysis_dependency_truncated = False
        self._source_lines = {
            ident: tree._lct_source.splitlines() for ident, tree in self.modules.items()
        }
        self._definitions_by_line = defaultdict(list)
        for ident, node in self.nodes.items():
            if ident in self.module_for:
                self._definitions_by_line[self.module_for[ident], node["definition_line"]].append(ident)
        self._definition_index_sizes = (len(self.nodes), len(self.module_for))
        for ident, tree in self.modules.items():
            deferred = any(
                isinstance(s, ast.ImportFrom)
                and s.module == "__future__"
                and any(a.name == "annotations" for a in s.names)
                for s in tree.body
            )
            self.inventory(tree, ident, ident, "module", deferred)
        self._unit_site_by_expr = {(s["execution_owner"], id(s["_expr"])):
                                   (s["site_id"], s["_expr"])
                                   for s in self.sites}
        self._unit_site_by_id = {s["site_id"]: (s["execution_owner"], s["_expr"])
                                 for s in self.sites}

        self._query_certificates = self._build_query_certificates()

        self._site_index_size = len(self.sites)
        self._site_keys = defaultdict(set)
        self._site_spellings = defaultdict(set)
        self._site_unqueried = set()
        self._site_no_atoms = set()
        self._site_targets = defaultdict(set)
        previous_sites = {(s["execution_owner"], s["line"], s["column"], s["kind"]): s
                          for s in (candidate_site_evidence or ())}
        selected_owners = frozenset(selected_owners or ())
        self._selected_owner_mode = bool(selected_owners)
        component_sites = {component: [] for component in (candidate_components or {}).values()}
        if self.candidate_components is not None:
            for pos, site in enumerate(self.sites):
                owner = self.module_for.get(site["execution_owner"])
                component = self.candidate_components.get(owner)
                if component is None:
                    # Unknown owners cannot be excluded from any candidate set.
                    self.candidate_components = None
                    component_sites.clear()
                    break
                component_sites[component].append(pos)
        self._component_site_order = dict(component_sites)
        self._component_site_positions = {key: frozenset(positions)
                                          for key, positions in component_sites.items()}
        for pos, site in enumerate(self.sites):
            if site["_call"] is None:
                continue
            self._site_unqueried.add(pos)
            expr = site["_expr"]
            old = previous_sites.get((site["execution_owner"], site["line"],
                                      site["column"], site["kind"]))
            if (site["execution_owner"] not in selected_owners and old is not None
                    and old.get("expression") == site["expression"]):
                if old.get("unknown_origin") or not old.get("complete"):
                    # Unknown and partial candidates must stay in the search.
                    pass
                else:
                    self._site_unqueried.discard(pos)
                for target in old["targets"]:
                    self._site_targets[target].add(pos)
            key = (self.module_for[site["execution_owner"]], expr.end_lineno,
                   expr.end_col_offset, False)
            self._site_keys[key].add(pos)
            spelling = (expr.id if isinstance(expr, ast.Name) else
                        expr.attr if isinstance(expr, ast.Attribute) else None)
            if spelling is not None:
                self._site_spellings[spelling].add(pos)
            if key in self.queries:
                self._observe_query(key, self.queries[key][0])
        self.effects = EffectCatalog(trees, self.execution_nodes)
        self._slot_scopes_by_origin, self._slot_fallback_scopes = self._index_local_slot_scopes()
        self.slot_scope_index_build_scopes = len(self.effects.slot_scopes)
        self.slot_scope_candidates_checked = 0
        self.slot_events_checked = 0
        self.value_reads = {}
        self.access = ReceiverAccess(self, Atom, Result)
        self._analysis_input_ready = True

    def _observe_analysis_input(self, scope, purpose, producer_scope=_SAME_INPUT_SCOPE,
                                *, consumer_scope=None):
        """Record one captured input range without changing semantic resolution."""
        if not self._analysis_input_ready:
            raise RuntimeError("Analysis input observed during Analyzer initialization")
        consumer_scope = (consumer_scope if consumer_scope is not None else
                          self.stack[-1][0] if self.stack else scope)
        consumer = self.module_for.get(consumer_scope)
        producer = self.module_for.get(scope if producer_scope is _SAME_INPUT_SCOPE
                                       else producer_scope)
        if consumer is None:
            self.analysis_inputs.truncated = True
            return
        component = (self.candidate_components.get(consumer)
                     if self.candidate_components is not None and
                     len(self.sites) == self._site_index_size else None)
        if component is not None and producer not in component:
            component = None
        self.analysis_inputs.observe(consumer, component, purpose)
        owner = self.stack[0][0] if self.stack else consumer_scope
        if owner in self.nodes:
            ident = self.analysis_inputs.component_ids.get(component) if component is not None else None
            members = () if ident is None else self._unit_component_members.get(ident)
            if ident is not None and members is None:
                members = tuple(sorted(self.analysis_inputs.members[ident]))
                self._unit_component_members[ident] = members
            self.unit_input_events.add((owner, consumer, members, purpose))

    def _record_analysis_dependency(self, destination, record):
        if record in destination:
            return
        if len(self.analysis_reads) + len(self.analysis_watches) >= ANALYSIS_DEPENDENCY_LIMIT:
            self.analysis_dependency_truncated = True
            return
        destination.add(record)

    def _unit_site(self, scope, expr, role):
        """Source-located private site for noncall reads/writes and returns."""
        existing = self._unit_site_by_expr.get((scope, id(expr)))
        if existing is not None and role == "call":
            return existing[0]
        module = self.nodes[self.module_for[scope]]
        return digest(canonical([module["repository"], module["path"],
                                 module["snapshot_id"], getattr(expr, "lineno", 0),
                                 getattr(expr, "col_offset", 0),
                                 getattr(expr, "end_lineno", 0),
                                 getattr(expr, "end_col_offset", 0), role]))

    def _unit_consumer(self, scope, expr):
        if self.stack:
            root_scope, root_expr, _ = self.stack[0]
            indexed = self._unit_site_by_expr.get((root_scope, root_expr))
            if indexed is not None:
                root = indexed[1]
                return root_scope, self._unit_site(root_scope, root, "call")
        return scope, self._unit_site(scope, expr, "read")

    def _unit_consumer_in(self, scope, expr):
        for owner, expression, _ in reversed(self.stack):
            if owner == scope and (owner, expression) in self._unit_site_by_expr:
                site, original = self._unit_site_by_expr[owner, expression]
                return site, original
        return self._unit_site(scope, expr, "read"), expr

    def _unit_record(self, collection, record):
        if self.unit_dependency_truncated:
            return
        if (len(self.unit_supports) + len(self.unit_container_subscriptions) +
                len(self.unit_container_writes) >= ORIGIN_LIMIT):
            self.unit_dependency_truncated = True
            return
        collection[canonical(record)] = record

    @staticmethod
    def _unit_expression(expr):
        if isinstance(expr, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return expr.name
        return ast.unparse(expr)[:240]

    @staticmethod
    def _unit_origin(atom):
        # The existing finite container model distinguishes constructor
        # allocations even when the dictionary expression is one __init__ AST.
        return atom.target if not atom.allocation else atom.target + "@" + atom.allocation

    def _unit_support(self, producer_owner, producer_expr, consumer_owner,
                      consumer_expr, kind, detail, status="observed", *,
                      producer_site=None, consumer_site=None):
        producer_site = producer_site or self._unit_site(producer_owner, producer_expr, "source")
        consumer_site = consumer_site or self._unit_site(consumer_owner, consumer_expr, "read")
        self._unit_record(self.unit_supports, dict(
            producer_owner=producer_owner, producer_site=producer_site,
            producer_location=dict(repository=self.nodes[producer_owner]["repository"],
                                   path=self.nodes[producer_owner]["path"],
                                   line=getattr(producer_expr, "lineno", 0),
                                   column=getattr(producer_expr, "col_offset", 0),
                                   end_line=getattr(producer_expr, "end_lineno", 0),
                                   end_column=getattr(producer_expr, "end_col_offset", 0),
                                   expression=self._unit_expression(producer_expr)),
            consumer_owner=consumer_owner, consumer_site=consumer_site,
            consumer_location=dict(repository=self.nodes[consumer_owner]["repository"],
                                   path=self.nodes[consumer_owner]["path"],
                                   line=getattr(consumer_expr, "lineno", 0),
                                   column=getattr(consumer_expr, "col_offset", 0),
                                   end_line=getattr(consumer_expr, "end_lineno", 0),
                                   end_column=getattr(consumer_expr, "end_col_offset", 0),
                                   expression=self._unit_expression(consumer_expr)),
            kind=kind, status=status, detail=detail))

    def _unit_write(self, origin, key_kind, key, owner, expr, kind, status):
        record = dict(origin=origin, key_kind=key_kind, key=key,
                      producer_owner=owner, producer_site=self._unit_site(owner, expr, "write"),
                      producer_location=dict(repository=self.nodes[owner]["repository"],
                                             path=self.nodes[owner]["path"],
                                             line=expr.lineno, column=expr.col_offset,
                                             end_line=expr.end_lineno,
                                             end_column=expr.end_col_offset,
                                             expression=self._unit_expression(expr)),
                      kind=kind, status=status)
        if canonical(record) not in self.unit_container_writes:
            self._unit_record(self.unit_container_writes, record)
            if not self.unit_dependency_truncated:
                self._unit_writes_by_origin[origin].append(record)
        return record

    def _unit_subscribe(self, origin, key_kind, key, scope, expr, reasons):
        # Resolution memo entries may be consumed by several distinct outer
        # call sites. Retain their actual reads for every later consumer.
        observation = (origin, key_kind, key, scope, expr, frozenset(reasons))
        for query in self.stack:
            self._unit_subscriptions_by_query[query][(origin, key_kind, key,
                                                        scope, id(expr))] = observation
        consumer_owner, consumer_site = self._unit_consumer(scope, expr)
        consumer_expr = self._unit_site_by_id.get(consumer_site, (consumer_owner, expr))[1]
        read_site = self._unit_site(scope, expr, "container-read")
        consumer_location = dict(repository=self.nodes[consumer_owner]["repository"],
                                 path=self.nodes[consumer_owner]["path"],
                                 line=consumer_expr.lineno, column=consumer_expr.col_offset,
                                 end_line=consumer_expr.end_lineno,
                                 end_column=consumer_expr.end_col_offset,
                                 expression=ast.unparse(consumer_expr)[:240])
        record = dict(origin=origin, key_kind=key_kind, key=key,
                      read_owner=scope, read_site=read_site,
                      read_location=dict(repository=self.nodes[scope]["repository"],
                                         path=self.nodes[scope]["path"],
                                         line=expr.lineno, column=expr.col_offset,
                                         end_line=expr.end_lineno,
                                         end_column=expr.end_col_offset,
                                         expression=ast.unparse(expr)[:240]),
                      consumer_owner=consumer_owner, consumer_site=consumer_site,
                      consumer_location=consumer_location,
                      unknown_reasons=sorted(reasons))
        self._unit_record(self.unit_container_subscriptions, record)
        for write in self._unit_writes_by_origin.get(origin, ()):
            if (key_kind == "exact" and write["key_kind"] == "exact"
                    and write["key"] != key):
                continue
            support = dict(producer_owner=write["producer_owner"],
                           producer_site=write["producer_site"],
                           producer_location=write["producer_location"],
                           consumer_owner=consumer_owner, consumer_site=consumer_site,
                           consumer_location=consumer_location,
                           kind="container-writer", status="candidate",
                           detail=dict(origin=origin, key_kind=key_kind, key=key,
                                       read_owner=scope, read_site=read_site,
                                       read_location=record["read_location"],
                                       write_kind=write["kind"],
                                       unknown_reasons=sorted(reasons)))
            self._unit_record(self.unit_supports, support)

    def _record_scope_read(self, producer_scope, kind, consumer_scope=None):
        """Record an observed cross-module read at the current evaluation scope."""
        if consumer_scope is None:
            consumer_scope = self.stack[-1][0] if self.stack else None
        producer = self.module_for.get(producer_scope)
        consumer = self.module_for.get(consumer_scope)
        if producer is not None and consumer is not None and producer != consumer:
            self._record_analysis_dependency(self.analysis_reads, (consumer, producer, kind))
            owner = self.stack[0][0] if self.stack else consumer_scope
            if owner in self.nodes:
                self.unit_analysis_reads.add((owner, consumer, producer, kind))

    def _record_query_targets(self, scope, raw):
        for record in raw:
            if record.get("target") in self.module_for and record.get("mapping") == "exact-captured-definition":
                self._record_scope_read(record["target"], "jedi-target", scope)

    def _index_local_slot_scopes(self):
        """Exclude only nonescaping, straight-line function-local containers.

        This is an admission proof for a scope, not an approximation of its
        receivers. A failed proof keeps the entire scope in the original scan.
        No resolution/Jedi work is performed while building this index.
        """
        by_origin = defaultdict(set)
        fallback = set()
        for scope in self.effects.slot_scopes:
            tree = self.trees[scope]
            if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fallback.add(scope)
                continue
            bindings = {}
            written = set()
            safe = True
            for stmt in tree.body:
                if isinstance(stmt, ast.Pass):
                    continue
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    continue
                if isinstance(stmt, ast.Return) and (stmt.value is None or
                        isinstance(stmt.value, ast.Constant)):
                    continue
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    safe = False
                    break
                dest, value = stmt.targets[0], stmt.value
                if isinstance(dest, ast.Name):
                    if isinstance(value, (ast.Dict, ast.List, ast.Tuple)):
                        parts = ([*value.keys, *value.values] if isinstance(value, ast.Dict)
                                 else value.elts)
                        if any(part is None or not isinstance(part, ast.Constant) for part in parts):
                            safe = False
                            break
                        bindings[dest.id] = f"{scope}:{value.lineno}:{value.col_offset}"
                    elif isinstance(value, ast.Name) and value.id in bindings:
                        bindings[dest.id] = bindings[value.id]
                    else:
                        safe = False
                        break
                elif (isinstance(dest, ast.Subscript) and isinstance(dest.value, ast.Name)
                      and dest.value.id in bindings and
                      isinstance(dest.ctx, ast.Store) and
                      self.literal_key(dest.slice)[0] and
                      isinstance(value, ast.Constant)):
                    written.add(bindings[dest.value.id])
                else:
                    safe = False
                    break
            if safe and written:
                for origin in written:
                    by_origin[origin].add(scope)
            else:
                fallback.add(scope)
        return by_origin, fallback

    def _observe_query(self, key, result):
        """Index only observations already made by the ordinary query path."""
        positions = self._site_keys.get(key, ())
        self._site_unqueried.difference_update(positions)
        if not result.atoms:
            self._site_no_atoms.update(positions)
        else:
            for atom in result.atoms:
                self._site_targets[atom.target].update(positions)

    def candidate_sites(self, function):
        """Preserve may_call's admission and original site order, including unknowns."""
        self._observe_analysis_input(function, "call-candidates", consumer_scope=function)
        component = self._candidate_component(function)
        if ((self._query_inflight and not self._selected_owner_mode) or
                len(self.sites) != self._site_index_size):
            return self.sites if component is None or len(self.sites) != self._site_index_size else self.sites_for(function)
        if component is None:
            positions = (self._site_spellings.get(self.nodes[function]["name"], set())
                         | self._site_targets.get(function, set())
                         | self._site_no_atoms | self._site_unqueried)
        else:
            allowed = self._component_site_positions[component]
            positions = ((self._site_spellings.get(self.nodes[function]["name"], set()) & allowed)
                         | (self._site_targets.get(function, set()) & allowed)
                         | (self._site_no_atoms & allowed) | (self._site_unqueried & allowed))
        return (self.sites[pos] for pos in sorted(positions))

    def _candidate_component(self, function):
        if self.candidate_components is None:
            return None
        module = self.module_for.get(function)
        component = self.candidate_components.get(module)
        if component not in self._component_site_positions:
            return None
        return component

    def sites_for(self, function):
        """The full ordered candidate universe within a certified component."""
        self._observe_analysis_input(function, "call-candidates", consumer_scope=function)
        component = self._candidate_component(function)
        if component is None or len(self.sites) != self._site_index_size:
            return self.sites
        return (self.sites[pos] for pos in self._component_site_order[component])

    def close(self):
        """Release only this analyzer's private captured sources."""
        self.temp.cleanup()

    def _build_query_certificates(self):
        """Scan each captured module once for uniquely bound direct declarations."""
        certificates = {}
        for module, tree in self.modules.items():
            declarations, unsafe_names = defaultdict(list), set()
            unsafe_module = False
            for obj in ast.walk(tree):
                if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    declarations[obj.name].append(obj)
                elif isinstance(obj, ast.Name) and isinstance(obj.ctx, (ast.Store, ast.Del)):
                    unsafe_names.add(obj.id)
                elif isinstance(obj, ast.arg):
                    unsafe_names.add(obj.arg)
                elif isinstance(obj, ast.alias):
                    if obj.name == "*":
                        unsafe_module = True
                    unsafe_names.add(obj.asname or obj.name.split(".")[0])
                elif isinstance(obj, (ast.Global, ast.Nonlocal)):
                    unsafe_names.update(obj.names)
                elif isinstance(obj, ast.ExceptHandler) and obj.name:
                    unsafe_names.add(obj.name)
                elif isinstance(obj, ast.Match):
                    # Captures have a separate binding grammar; decline the module.
                    unsafe_module = True
                elif isinstance(obj, ast.Call) and isinstance(obj.func, ast.Name) and obj.func.id in (
                    "eval", "exec", "locals", "globals", "vars"
                ):
                    unsafe_module = True
            if unsafe_module:
                continue
            for name, matches in declarations.items():
                if len(matches) != 1 or name in unsafe_names:
                    continue
                obj = matches[0]
                target = self.owner.get(id(obj))
                if target is None or self.nodes[target]["name"] != name:
                    continue
                parent = self.nodes[target]["parent"]
                owner = self.trees.get(parent)
                if (not isinstance(owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef))
                        or obj not in owner.body or obj.decorator_list):
                    continue
                if isinstance(obj, ast.ClassDef):
                    if obj.bases or obj.keywords:
                        continue
                elif (any(not isinstance(default, ast.Constant) for default in obj.args.defaults)
                      or any(default is not None and not isinstance(default, ast.Constant)
                             for default in obj.args.kw_defaults)):
                    continue
                certificates[module, name] = target, parent
        return certificates

    def _direct_lexical_query(self, scope, expr, result, raw, *, local_only=False):
        """Proof for one direct local name; opaque imported/assigned origins are excluded."""
        if not isinstance(expr, ast.Name) or len(raw) != 1 or len(result.atoms) != 1 or result.requirements:
            return False
        module = self.module_for[scope]
        certificate = self._query_certificates.get((module, expr.id))
        if certificate is None:
            return False
        target, owner = certificate
        if local_only and isinstance(self.trees[owner], ast.Module):
            # Other Python modules may write a module global. Function locals
            # cannot be rebound from another captured module's lexical body.
            return False
        atom = next(iter(result.atoms))
        record = raw[0]
        if (atom.target != target or atom.kind not in ("callable", "class")
                or record.get("mapping") != "exact-captured-definition"
                or record.get("target") != target or record.get("name") != expr.id
                or record.get("source_sha256") != self.nodes[target]["source_sha256"]):
            return False
        current = scope
        while current != owner:
            current = self.nodes[current]["parent"]
            if current is None or current not in self.nodes or current == module and owner != module:
                return False
        return True

    def inventory(self, obj, lexical, execution, phase, deferred):
        """Record syntax positions and definition-time execution owners."""
        self.execution_nodes[id(obj)] = (execution, phase)
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
            self.inventory(obj.target, lexical, execution, phase, deferred)
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
        if module is not None and module not in self.modules:
            owner = self.nodes[module]
            raise RequiredAnalysisContext(owner["repository"], owner["path"])
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
        lines = self._source_lines[module]
        col = len(lines[name.line - 1][: name.column].encode("utf-8")) if name.line else None
        matches = []
        candidates = (
            self._definitions_by_line.get((module, name.line), ())
            if (len(self.nodes), len(self.module_for)) == self._definition_index_sizes
            else (
                ident for ident, node in self.nodes.items()
                if self.module_for.get(ident) == module and node["definition_line"] == name.line
            )
        )
        for ident in candidates:
            node = self.nodes[ident]
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
            receiver_matches = []
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
                        # Jedi may point an imported binding to a later subscript
                        # mutation. Its named receiver is the container binding;
                        # the assignment value is the *slot* value, not the import.
                        for target in targets:
                            if (isinstance(target, ast.Subscript)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id == name.name
                                    and target.value.lineno == name.line
                                    and target.value.col_offset == col):
                                receiver_matches.append((scope, statement, target.value))
            if len(receiver_matches) == 1:
                scope, statement, receiver = receiver_matches[0]
                # Resolve strictly before the write, so the current assignment
                # cannot become its own origin. Unknown/ambiguous/custom receivers
                # remain unknown and do not certify a dictionary target.
                origin = self.resolve(scope, receiver,
                                      before=(statement.lineno, statement.col_offset))
                if (len(origin.atoms) == 1 and not origin.unknown
                        and all(atom.kind == "container"
                                and atom.target in self.container_exprs
                                and isinstance(self.container_exprs[atom.target][1], ast.Dict)
                                for atom in origin.atoms)
                        and self.requirements_complete(origin)):
                    raw["mapping"] = "exact-captured-subscript-receiver"
                    return origin, raw
                raw["mapping"] = "uncertain-captured-subscript-receiver"
                return union(origin, unknown("uncertain-captured-subscript-receiver")), raw
            if receiver_matches:
                raw["mapping"] = "ambiguous-captured-subscript-receiver"
                return unknown("ambiguous-captured-subscript-receiver"), raw
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
        self._observe_analysis_input(scope, "jedi-query")
        key = (module, expr.end_lineno, expr.end_col_offset, goto)
        if key in self.queries:
            self._record_query_targets(scope, self.queries[key][1])
            return self.queries[key][0]
        self._query_context[key] = (scope, expr)
        cached = self.query_reuse.get(key)
        if cached is not None:
            result, previous_raw = cached
            # The old observation is admitted only for unchanged captured Python.
            # Rebind snapshot-scoped evidence from freshly extracted definitions.
            raw = [dict(record) for record in previous_raw]
            if self._direct_lexical_query(
                scope, expr, result, raw,
                local_only=getattr(self.query_reuse, "python_changed", False),
            ):
                for record in raw:
                    if "target" in record:
                        record["version_id"] = self.nodes[record["target"]]["version_id"]
                self.queries[key] = result, raw
                self._observe_query(key, result)
                self._record_query_targets(scope, raw)
                self.reused_queries += 1
                return result
        line = self._source_lines[module][expr.end_lineno - 1]
        column = len(line.encode("utf-8")[: expr.end_col_offset].decode("utf-8"))
        raw, results = [], []
        self._query_inflight += 1
        try:
            script = self.scripts[module]
            self.executed_queries += 1
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
        except RequiredAnalysisContext:
            raise
        except Exception as exc:
            raw.append(dict(error=type(exc).__name__, mapping="jedi-error"))
            results.append(unknown("jedi-error:" + type(exc).__name__))
        finally:
            self._query_inflight -= 1
        result = union(*results) if results else unknown("jedi-no-result")
        if not goto and any(a.kind in ("callable", "class", "instance") for a in result.atoms):
            result = union(result, unknown("jedi-inference-not-exhaustive"))
        self.queries[key] = result, raw
        self._observe_query(key, result)
        self._record_query_targets(scope, raw)
        return result

    def reusable_queries(self):
        """Only side-effect-free, captured-definition observations can cross snapshots."""
        records = []
        for key, (result, raw) in self.queries.items():
            context = self._query_context.get(key)
            if context is None or not self._direct_lexical_query(*context, result, raw):
                continue
            records.append(dict(key=list(key), execution_owner=context[0],
                atoms=[vars(a) for a in sorted(
                result.atoms, key=lambda a: (a.kind, a.target, a.bound, a.receiver, a.allocation))],
                reasons=sorted(result.reasons), proofs=sorted(result.proofs), raw=raw))
        return records

    def reaching(self, scope, name, before):
        """Select one name's reaching bindings, killing unconditional older values.

        If alternatives are unioned. Loops/try/match writes remain unknown. There is
        no execution environment, path simulation, heap or convergence algorithm.
        """
        self._observe_analysis_input(scope, "lexical-lookup")
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
        self._observe_analysis_input(scope, "resolve-input")
        if expr is None:
            return unknown("missing-value")
        before = before if before is not None else (expr.lineno, expr.col_offset)
        key = (scope, id(expr), before)
        if self.stack:
            deps = self.dependencies.setdefault(self.stack[-1], [])
            if key not in deps:
                deps.append(key)
        if key in self.memo:
            for observation in tuple(self._unit_subscriptions_by_query.get(key, {}).values()):
                self._unit_subscribe(*observation)
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
        if (scope, id(expr)) in self.coverage and not (
            result.atoms and all(a.kind in ("boundary", "external-value") for a in result.atoms)
        ):
            result = Result(
                result.atoms,
                result.reasons,
                result.proofs,
                result.requirements | {(scope, id(expr))},
            )
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
                    if self.invocation_phase(a) != "ordinary-call":
                        results.append(
                            Result(
                                frozenset(
                                    [
                                        Atom(
                                            "deferred-result",
                                            a.target,
                                            receiver=a.receiver,
                                            allocation=a.allocation,
                                        )
                                    ]
                                ),
                                frozenset(["deferred-call-result-not-modeled"]),
                            )
                        )
                        continue
                    obj = self.trees[a.target]
                    returns = [obj.body] if isinstance(obj, ast.Lambda) else self.return_values(obj)
                    for returned in returns:
                        value = self.resolve(a.target, returned)
                        results.append(value)
                        self._unit_support(a.target, returned, scope, expr,
                                           "return-value", dict(
                                               call_expression=ast.unparse(expr),
                                               target_ids=sorted(atom.target for atom in value.atoms
                                                                 if atom.kind in CALLABLE_KINDS),
                                               unknown_reasons=sorted(value.reasons)),
                                           "unknown" if value.unknown else "observed")
            if results:
                return union(
                    *results,
                    unknown("unknown-call-result") if targets.unknown else Result(),
                    Result(requirements=targets.requirements),
                )
            return self.query(scope, expr)
        return self.query(scope, expr)

    def return_values(self, obj):
        """Collect direct return expressions without entering nested definitions."""
        self._record_scope_read(self.owner.get(id(obj)), "return-body")
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
        self._observe_analysis_input(scope, "lexical-lookup")
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
            return Result(frozenset(atoms), value.reasons, value.proofs, value.requirements)
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
        self._observe_analysis_input(scope, "member-lookup")
        receivers = self.resolve(scope, expr.value)
        cov = self.coverage_models.setdefault(
            (scope, id(expr)), EffectCoverage("instance-field-coverage")
        )
        results = []
        for receiver in receivers.atoms:
            if receiver.kind not in ("instance", "class", "module", "super"):
                continue
            value = self.member(receiver.target, expr.attr, skip_own=receiver.kind == "super")
            if receiver.kind == "instance":
                guard = self.descriptor_guard(receiver.target, expr.attr, value)
                if guard:
                    cov.gaps.append(guard)
                    results.append(union(self.query(scope, expr), unknown(guard)))
                    continue
                field = self.instance_field(receiver, expr.attr, scope, expr)
                if field is not None:
                    if any(a.kind == "absent-field" for a in field.atoms):
                        field = Result(
                            frozenset(a for a in field.atoms if a.kind != "absent-field"),
                            field.reasons,
                            field.proofs,
                            field.requirements,
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
                            field = union(
                                field,
                                Result(fallback, value.reasons, value.proofs, value.requirements),
                            )
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
                        field = union(
                            field,
                            Result(alternatives, value.reasons, value.proofs, value.requirements),
                        )
                    results.append(certified(field, "python-instance-field-precedence"))
                    continue
            if value is not None:
                cov.source(
                    "nondata-member-source",
                    bool(value.proofs) and not value.unknown and self.requirements_complete(value),
                )
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
                        Result(frozenset(atoms), value.reasons, value.proofs, value.requirements),
                        "python-nondata-member-lookup",
                    )
                )
        if results:
            result = union(*results, unknown("unknown-receiver") if receivers.unknown else Result())
            cov.source(
                "receiver-origin",
                bool(receivers.atoms)
                and not receivers.unknown
                and self.requirements_complete(receivers),
            )
            self.coverage[(scope, id(expr))] = cov.export()
            return result
        result = self.query(scope, expr)
        cov.gaps.append("unresolved-attribute-source")
        self.coverage[(scope, id(expr))] = cov.export()
        return Result(
            result.atoms, result.reasons | receivers.reasons, result.proofs, result.requirements
        )

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
        initializer = self.member(owner, "__init__")
        if initializer and any(
            self.invocation_phase(a) != "ordinary-call" for a in initializer.atoms
        ):
            return "unsupported-deferred-initializer"
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

    def invocation_phase(self, atom):
        """Classify creation of suspended bodies without running or scheduling them."""
        if atom.kind in ("context-factory", "async-context-factory"):
            return "context-manager-create"
        tree = self.trees.get(atom.target)
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return "ordinary-call"
        generator = any(
            isinstance(e.node, (ast.Yield, ast.YieldFrom))
            for e in self.effects.by_scope.get(atom.target, [])
        )
        if isinstance(tree, ast.AsyncFunctionDef):
            return "async-generator-create" if generator else "coroutine-create"
        return "generator-create" if generator else "ordinary-call"

    def method_target(self, receiver, scope, call):
        """Resolve this access before the call, including direct instance overrides."""
        tree = self.trees[scope]
        params = (
            tree.args.posonlyargs + tree.args.args
            if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
            else []
        )
        constructor_self = (
            self.nodes[scope]["name"] == "__init__"
            and params
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == params[0].arg
        )
        if not constructor_self:
            return self.resolve(scope, call.func)
        method = call.func.attr
        member = self.member(receiver.target, method)
        guard = self.descriptor_guard(receiver.target, method, member)
        if guard:
            return unknown(guard)
        field = self.instance_field(receiver, method, scope, call.func)
        if field is not None and not any(a.kind == "absent-field" for a in field.atoms):
            return field
        if member is None:
            return unknown("unresolved-receiver-method-target")
        bound = frozenset(
            Atom(a.kind, a.target, a.kind == "callable", receiver.target, receiver.allocation)
            for a in member.atoms
        )
        value = Result(bound, member.reasons, member.proofs, member.requirements)
        if field is not None:
            value = union(
                value,
                Result(
                    frozenset(a for a in field.atoms if a.kind != "absent-field"),
                    field.reasons,
                    field.proofs,
                    field.requirements,
                ),
            )
        return value

    def method_field_effect(self, receiver, scope, call, name):
        """Check actual dispatch, phase and receiver stability before using a summary."""
        targets = self.method_target(receiver, scope, call)
        detail = dict(
            kind="method-effect-applicability",
            scope=scope,
            line=call.lineno,
            receiver=receiver.target,
            allocation=receiver.allocation,
            targets=sorted(a.target for a in targets.atoms if a.kind in CALLABLE_KINDS),
            decision="unsupported",
            unknown_reasons=sorted(targets.reasons),
        )
        self.method_effects[(scope, id(call), receiver.allocation, name)] = detail

        def outcome(kind, reason, value=None):
            return EffectOutcome(kind, reason, value, detail)

        if targets.unknown or len(targets.atoms) != 1 or not self.requirements_complete(targets):
            return outcome(
                EffectKind.UNKNOWN_EFFECT,
                "unproven-callsite-method-target",
                union(unknown("unproven-callsite-method-target"), Result(reasons=targets.reasons)),
            )
        atom = next(iter(targets.atoms))
        phase = self.invocation_phase(atom)
        detail["invocation_phase"] = phase
        if phase != "ordinary-call":
            detail["decision"] = "deferred-body-not-executed"
            return outcome(EffectKind.NO_EFFECT, "deferred-body-not-executed")
        if atom.bound and atom.allocation and atom.allocation != receiver.allocation:
            detail["decision"] = "other-receiver-body-summary"
            return outcome(EffectKind.NO_EFFECT, "independent-receiver")
        tree = self.trees.get(atom.target)
        if (
            atom.kind != "callable"
            or not isinstance(tree, (ast.FunctionDef, ast.Lambda))
            or getattr(tree, "decorator_list", [])
        ):
            return outcome(EffectKind.UNKNOWN_EFFECT, "unsupported-receiver-method-effects")
        if "constructor-field-origin" in targets.proofs:
            return outcome(
                EffectKind.UNKNOWN_EFFECT, "constructor-shadowed-receiver-method-effects"
            )
        params = tree.args.posonlyargs + tree.args.args + tree.args.kwonlyargs
        receiver_name = params[0].arg if params and atom.bound else None
        if atom.bound and (not atom.allocation or not receiver_name):
            return outcome(EffectKind.UNKNOWN_EFFECT, "unproven-method-receiver-binding")
        detail["body_receiver_allocation"] = atom.allocation
        detail["decision"] = "finite-body-summary"
        cov = EffectCoverage("finite-method-summary")
        cov.source("verified-call-target-and-phase", True)
        value = self.field_scope(receiver, name, atom.target, None, receiver_name, cov)
        detail["summary_coverage"] = cov.export()
        returns = [
            e
            for e in self.effects.by_scope[atom.target]
            if e.kind == "terminate" and e.reachable and not e.conditional
        ]
        if returns:
            detail["termination_line"] = returns[0].node.lineno
            detail["decision"] = "return-terminated-summary"
        if not valid_coverage(detail["summary_coverage"]):
            reasons = [
                c["reason"]
                for c in detail["summary_coverage"]["checks"]
                if c["outcome"] == EffectKind.UNKNOWN_EFFECT.value
            ]
            return outcome(
                EffectKind.UNKNOWN_EFFECT,
                reasons[0] if reasons else "incomplete-method-effect-coverage",
                value,
            )
        if value is None:
            return outcome(EffectKind.NO_EFFECT, "verified-body-without-field-effect")
        return outcome(EffectKind.KNOWN_EFFECT, "finite-body-summary", value)

    def effect_owners(self, receiver, scope, expr, receiver_name):
        """Specialize only the stable bound parameter; other values use existing resolution."""
        if receiver_name and isinstance(expr, ast.Name) and expr.id == receiver_name:
            return Result(frozenset([receiver]), proofs=frozenset(["bound-receiver-origin"]))
        return self.resolve(scope, expr)

    def receiver_relation(self, receiver, values):
        """A missing allocation is an association gap, never proof of independence."""
        instances = [a for a in values.atoms if a.kind in ("instance", "deferred-result")]
        supported_reasons = {"deferred-call-result-not-modeled"}
        if any(a.allocation == receiver.allocation and a.allocation for a in instances):
            return (
                "same"
                if all(a.allocation == receiver.allocation for a in instances)
                and not (values.reasons - supported_reasons)
                else "unknown"
            )
        if (
            instances
            and all(a.allocation for a in instances)
            and not (values.reasons - supported_reasons)
        ):
            return "independent"
        if not instances and values.atoms and not values.unknown:
            return "non-receiver"
        return "unknown"

    def event_bindings(self, node):
        """Identify implicit binding syntax without evaluating its protocol or values."""
        targets = []
        if isinstance(node, (ast.For, ast.AsyncFor)):
            targets = [node.target]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            targets = [i.optional_vars for i in node.items if i.optional_vars]
        names = {
            n.id
            for t in targets
            for n in ast.walk(t)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
        }
        if isinstance(
            node, (ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            if node.name:
                names.add(node.name)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        if isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
        return names

    def call_field_effect(self, event, receiver, name, receiver_name=None):
        """Certify call effects only from complete access checks or a verified body summary."""
        call, scope = event.node, event.scope
        frames = {scope: call}
        bindings = (
            {
                (scope, receiver_name): Result(
                    frozenset([receiver]), proofs=frozenset(["bound-receiver-origin"])
                )
            }
            if receiver_name
            else {}
        )
        origin = self.allocations.get(receiver.allocation)
        targets = self.method_target(receiver, scope, call)
        resolved = (
            bool(targets.atoms)
            and not targets.unknown
            and self.requirements_complete(targets)
            and all(a.kind in CALLABLE_KINDS for a in targets.atoms)
        )
        proof = dict(
            target_state="RESOLVED" if resolved else "UNKNOWN",
            targets=sorted(a.target for a in targets.atoms if a.kind in CALLABLE_KINDS),
            entries=[],
            definitions=[
                dict(target=a.target, version_id=self.nodes[a.target]["version_id"])
                for a in targets.atoms
                if a.kind in CALLABLE_KINDS
            ],
        )
        detail = dict(call_access=proof)

        def no(reason, basis="all-inputs-disproved"):
            return EffectOutcome(
                EffectKind.NO_EFFECT, reason, detail=dict(detail, no_effect_basis=basis)
            )

        def bad(reason):
            return EffectOutcome(EffectKind.UNKNOWN_EFFECT, reason, detail=detail)

        # A fresh source allocation cannot be accessed before it exists. Constructor
        # effects for this very creation are separately required by instance_field.
        if origin and origin[0] == scope and call is origin[1] and resolved:
            proof["allocation"] = receiver.allocation
            return no("construction-accounted-in-field-scope", "construction")
        if origin and origin[0] == scope:
            creation = self.effects.points.get((scope, id(origin[1])))
            if creation is not None and event.order < creation:
                proof.update(
                    target_state="BEFORE_ALLOCATION",
                    allocation=receiver.allocation,
                    event_order=event.order,
                    creation_order=creation,
                )
                return no("call-precedes-instance-creation", "creation-order")

        entries = []
        for arg in call.args:
            entries.append(
                self.access.reachable(scope, arg, receiver, call, frames=frames, bindings=bindings)
            )
        for kw in call.keywords:
            entries.append(
                self.access.reachable(
                    scope,
                    kw.value,
                    receiver,
                    call,
                    mode="kwargs" if kw.arg is None else "value",
                    frames=frames,
                    bindings=bindings,
                )
            )
        proof["entries"] = [e.export() for e in entries]
        if any(
            a.kind == "deferred-result" and a.allocation == receiver.allocation
            for arg in call.args + [k.value for k in call.keywords]
            for a in self.access.value(scope, arg, frames, bindings).atoms
        ):
            return bad("deferred-method-resumption-not-modeled")
        if not resolved:
            argument_access = combine(entries, "argument-access")
            if argument_access.state == AccessKind.REACHABLE:
                return bad("instance-argument-escape")
            if argument_access.state == AccessKind.UNKNOWN:
                return bad(
                    "unresolved-call-access:"
                    + (argument_access.gaps[0] if argument_access.gaps else "unresolved-origin")
                )
            private = self.access.private_input(scope, call, receiver, entries)
            if private:
                proof.update(target_state="PREEXISTING_INPUT", private_input=private)
                return no("preexisting-input-cannot-access-private-allocation", "private-input")
            return bad("unresolved-call-target-access")
        phases = [self.invocation_phase(a) for a in targets.atoms]
        proof["phases"] = phases
        if all(p != "ordinary-call" for p in phases):
            # The body cannot run at creation, even if inputs retain this receiver.
            # Nested operand calls have independent earlier catalog events.
            effect = self.method_field_effect(receiver, scope, call, name)
            return EffectOutcome(
                effect.kind,
                effect.reason,
                effect.value,
                dict(effect.detail, **detail, no_effect_basis="deferred-creation"),
            )
        same = any(a.bound and a.allocation == receiver.allocation for a in targets.atoms)
        if isinstance(call.func, ast.Attribute):
            owners = self.effect_owners(receiver, scope, call.func.value, receiver_name)
            surface = self.receiver_relation(receiver, owners)
            if surface == "same" and not any(a.bound for a in targets.atoms):
                same = True
            elif surface == "unknown":
                entries.append(access(AccessKind.UNKNOWN, "unresolved-bound-receiver"))
        dependencies = []
        body_dependencies = []
        for atom in targets.atoms:
            if atom.bound and atom.allocation != receiver.allocation:
                bound_value = Result(
                    frozenset(
                        [
                            Atom(
                                "class"
                                if any(
                                    ast.unparse(d) == "classmethod"
                                    for d in getattr(
                                        self.trees.get(atom.target), "decorator_list", []
                                    )
                                )
                                else "instance",
                                atom.receiver,
                                allocation=atom.allocation,
                            )
                        ]
                    ),
                    proofs=frozenset(["bound-receiver-origin"]),
                )
                dependencies.append(
                    self.access.values(
                        bound_value,
                        scope,
                        receiver,
                        call,
                        mode="receiver",
                        frames=frames,
                        bindings=bindings,
                    )
                )
            body_start = len(dependencies)
            if atom.kind == "class":
                dependencies.append(
                    self.access.constructed(atom.target, scope, call, receiver, frames, bindings)
                )
            else:
                dependencies.append(
                    self.access.function(
                        atom, scope, call, receiver, frames, bindings, environment_only=same
                    )
                )
            body_dependencies.extend(dependencies[body_start:])
        if all(
            a.kind == "callable" and not self.access.summary(a.target)["used_params"]
            for a in targets.atoms
        ) and all(d.state == AccessKind.NOT_REACHABLE for d in body_dependencies):
            target = next(iter(targets.atoms))
            body_receiver = (
                Atom("instance", target.receiver, allocation=target.allocation)
                if target.bound and target.allocation
                else receiver
            )
            effect = self.method_field_effect(body_receiver, scope, call, name)
            if effect.kind == EffectKind.NO_EFFECT and valid_coverage(
                effect.detail.get("summary_coverage")
            ):
                proof["unused_inputs"] = dict(
                    used_parameters=[],
                    dependencies=[d.export() for d in body_dependencies],
                    ignored_inputs=[d.export() for d in dependencies if d not in body_dependencies],
                )
                return EffectOutcome(
                    effect.kind,
                    effect.reason,
                    effect.value,
                    dict(effect.detail, **detail, no_effect_basis="unused-input-summary"),
                )
        entries.extend(dependencies)
        proof["entries"] = [e.export() for e in entries]
        state = combine(entries, "call-access-entries")
        if state.state == AccessKind.REACHABLE:
            reason = (
                "captured-receiver-effects-not-modeled"
                if any(
                    e.get("reason") in ("closure-binding", "external-binding")
                    for e in state.evidence
                )
                else "instance-argument-escape"
            )
            return bad(reason)
        if state.state == AccessKind.UNKNOWN:
            return bad(
                "unresolved-call-access:" + (state.gaps[0] if state.gaps else "unresolved-origin")
            )
        if same:
            effect = self.method_field_effect(receiver, scope, call, name)
            return EffectOutcome(
                effect.kind,
                effect.reason,
                effect.value,
                dict(effect.detail, **detail, no_effect_basis="method-summary"),
            )
        return no("call-access-proved-unrelated")

    def field_event(self, event, receiver, name, receiver_name=None):
        """Classify every inventory event; unsupported relevant operations default unknown."""
        node, scope = event.node, event.scope

        def no(reason):
            return EffectOutcome(EffectKind.NO_EFFECT, reason)

        def bad(reason):
            return EffectOutcome(EffectKind.UNKNOWN_EFFECT, reason)

        if not event.reachable:
            return no("unreachable-after-termination")
        if event.kind == "binding":
            return (
                bad("receiver-binding-changed")
                if receiver_name in self.event_bindings(node)
                else no("binding-does-not-replace-receiver")
            )
        if event.kind == "implicit-call":
            return bad("implicit-decorator-effects-not-modeled")
        if event.kind == "terminate":
            return (
                bad("conditional-termination-not-modeled")
                if event.conditional
                else no("scope-termination")
            )
        if event.kind == "write":
            if isinstance(node, ast.AnnAssign) and node.value is None:
                return no("annotation-without-store")
            targets = [node.target] if isinstance(node, ast.NamedExpr) else self.write_targets(node)
            if receiver_name and any(
                isinstance(n, ast.Name) and n.id == receiver_name
                for t in targets
                for n in ast.walk(t)
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
            ):
                return bad("receiver-binding-changed")
            if receiver_name and (
                isinstance(node, ast.AugAssign)
                and any(isinstance(t, ast.Name) for t in targets)
                or any(isinstance(t, (ast.Tuple, ast.List)) for t in targets)
            ):
                return bad("unsupported-summary-binding")
            for dest in targets:
                if isinstance(dest, (ast.Tuple, ast.List)):
                    if any(isinstance(n, (ast.Attribute, ast.Subscript)) for n in ast.walk(dest)):
                        return bad("unsupported-unpacked-field-write")
                    continue
                if not isinstance(dest, ast.Attribute) or dest.attr != name:
                    continue
                owners = self.effect_owners(receiver, scope, dest.value, receiver_name)
                relation = self.receiver_relation(receiver, owners)
                if relation == "independent" or relation == "non-receiver":
                    continue
                if relation != "same":
                    return bad("unproven-field-write-receiver")
                if isinstance(node, ast.AugAssign):
                    return bad("unsupported-instance-augassign")
                rhs = getattr(node, "value", None)
                candidate = (
                    self.field_value(scope, rhs, receiver.allocation)
                    if receiver_name and rhs
                    else self.resolve(scope, rhs)
                    if rhs
                    else known("absent-field", name)
                )
                if isinstance(node, ast.Delete):
                    candidate = known("absent-field", name)
                if (
                    candidate.unknown
                    or not candidate.proofs
                    or not self.requirements_complete(candidate)
                ):
                    return EffectOutcome(
                        EffectKind.UNKNOWN_EFFECT, "unproven-field-value", candidate
                    )
                return EffectOutcome(
                    EffectKind.KNOWN_EFFECT, "direct-field-store-or-delete", candidate
                )
            return no("write-does-not-rebind-queried-field-or-receiver")
        if event.kind == "await":
            resumed = self.resolve(scope, node.value)
            relation = self.receiver_relation(receiver, resumed)
            if relation in ("independent", "non-receiver"):
                return no("independent-deferred-resumption")
            return bad(
                "deferred-method-resumption-not-modeled"
                if relation == "same"
                else "deferred-receiver-association-gap"
            )
        if event.kind == "call":
            effect = self.call_field_effect(event, receiver, name, receiver_name)
            self.access.call_records[(scope, id(event.node), receiver.allocation)] = effect
            return effect
        if event.kind == "region":
            return bad("unsupported-protocol-region")
        if event.kind == "scope-execution":
            return implicit_execution_effect(event)
        return bad("missing-effect-handler")

    def field_scope(self, receiver, name, scope, anchor, receiver_name, coverage, initial=None):
        """Consume the reused scope catalog, with a disposition for every required event."""
        value = initial
        binding_failure = None
        for event in self.effects.before(scope, anchor):
            coverage.require(event)
            if binding_failure:
                coverage.record(
                    event,
                    EffectOutcome(
                        EffectKind.UNKNOWN_EFFECT if event.reachable else EffectKind.NO_EFFECT,
                        binding_failure if event.reachable else "unreachable-after-termination",
                    ),
                )
                continue
            effect = self.field_event(event, receiver, name, receiver_name)
            if not isinstance(effect, EffectOutcome):
                effect = EffectOutcome(EffectKind.UNKNOWN_EFFECT, "missing-effect-handler")
            coverage.record(event, effect)
            if effect.detail:
                coverage.events.append(effect.detail)
            if effect.kind == EffectKind.NO_EFFECT:
                continue
            coverage.events.append(dict(event.location(), reason=effect.reason))
            candidate = effect.value or unknown(effect.reason)
            if effect.kind == EffectKind.UNKNOWN_EFFECT:
                if value is None and effect.reason in {
                    "implicit-decorator-effects-not-modeled",
                    "unsupported-protocol-region",
                    "unsupported-class-definition-effects",
                }:
                    # Unsupported execution may leave the absent instance field unchanged.
                    # Retain the existing class-member fallback as a partial alternative.
                    value = known("absent-field", name)
                if effect.reason.startswith("deferred-"):
                    value = union(candidate, unknown(effect.reason))
                else:
                    value = union(value or Result(), candidate, unknown(effect.reason))
                if effect.reason in ("receiver-binding-changed", "unsupported-summary-binding"):
                    # Refuse the remainder; no later write can rely on unstable summary bindings.
                    coverage.gaps.append(effect.reason)
                    binding_failure = effect.reason
            elif event.conditional or not event.ordered:
                value = union(
                    value or known("absent-field", name),
                    candidate,
                    unknown("conditional-instance-field"),
                )
                coverage.outcomes[event.ident]["outcome"] = EffectKind.UNKNOWN_EFFECT.value
                coverage.outcomes[event.ident]["reason"] = "conditional-instance-field"
            else:
                value = candidate
        return value

    def instance_field(self, receiver, name, scope, anchor):
        """Read constructor and callsite effects through the same event/coverage mechanism."""
        cov = self.coverage_models.setdefault(
            (scope, id(anchor)), EffectCoverage("instance-field-coverage")
        )
        value = None
        initializer = self.member(receiver.target, "__init__")
        cov.source("supported-construction-protocol", not initializer or not initializer.unknown)
        if initializer:
            for function in initializer.atoms:
                tree = self.trees.get(function.target)
                if function.kind != "callable" or not isinstance(tree, ast.FunctionDef):
                    cov.gaps.append("unsupported-constructor-summary")
                    value = unknown("unsupported-constructor-summary")
                    continue
                args = tree.args.posonlyargs + tree.args.args
                receiver_name = args[0].arg if args else None
                initial = self.field_scope(
                    receiver,
                    name,
                    function.target,
                    anchor if scope == function.target else None,
                    receiver_name,
                    cov,
                )
                if initial is not None:
                    value = certified(initial, "constructor-field-origin")
        value = self.field_scope(receiver, name, scope, anchor, None, cov, value)
        self.coverage[(scope, id(anchor))] = cov.export()
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
            value.requirements,
        )

    def requirements_complete(self, result):
        """Proof labels do not satisfy unresolved event/source coverage dependencies."""
        return all(valid_coverage(self.coverage.get(key)) for key in result.requirements)

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
            for site in self.candidate_sites(scope):
                if site["_call"] is None or not self.may_call(scope, site):
                    continue
                for a in self.resolve(site["execution_owner"], site["_expr"]).atoms:
                    if a.kind == "callable" and a.target == scope and a.bound and a.receiver:
                        self._record_scope_read(site["execution_owner"], "parameter-origin", scope)
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
                for site in (self.candidate_sites(parent) if self._selected_owner_mode
                             else self.sites_for(scope)):
                    if site["_call"] is None:
                        continue
                    callee = self.resolve(site["execution_owner"], site["_expr"])
                    if any(a.kind == "class" and a.target == parent for a in callee.atoms):
                        self._record_scope_read(site["execution_owner"], "parameter-origin", scope)
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
        for site in self.candidate_sites(scope):
            call = site["_call"]
            if call is None or not self.may_call(scope, site):
                continue
            targets = self.resolve(site["execution_owner"], site["_expr"])
            for a in targets.atoms:
                if a.target != scope or a.kind != "callable":
                    continue
                self._record_scope_read(site["execution_owner"], "parameter-origin", scope)
                positional = params[1:] if a.bound else params
                index = next((i for i, p in enumerate(positional) if p.arg == param.arg), None)
                arg = call.args[index] if index is not None and index < len(call.args) else None
                if isinstance(arg, ast.Starred) or any(kw.arg is None for kw in call.keywords):
                    results.append(unknown("argument-unpacking"))
                    use_site, use_expr = self._unit_consumer_in(scope, param)
                    self._unit_support(site["execution_owner"], call, scope, use_expr,
                                       "actual-parameter", dict(
                                           parameter=dict(name=param.arg, index=index,
                                                          kind="keyword-only" if param in t.args.kwonlyargs
                                                          else "positional"),
                                           argument_source=dict(kind="unpacking",
                                                                call_site=site["site_id"],
                                                                expression=ast.unparse(call)),
                                           target_ids=[],
                                           unknown_reasons=["argument-unpacking"]),
                                       "unknown", producer_site=site["site_id"],
                                       consumer_site=use_site)
                else:
                    arg = next((kw.value for kw in call.keywords if kw.arg == param.arg), arg)
                    if arg is not None:
                        supplied = self.resolve(site["execution_owner"], arg)
                        results.append(supplied)
                        use_site, use_expr = self._unit_consumer_in(scope, param)
                        self._unit_support(site["execution_owner"], arg, scope, use_expr,
                                           "actual-parameter", dict(
                                               parameter=dict(name=param.arg, index=index,
                                                              kind="keyword" if any(
                                                                  kw.arg == param.arg for kw in call.keywords)
                                                              else "positional"),
                                               argument_source=dict(kind="keyword" if any(
                                                   kw.arg == param.arg for kw in call.keywords)
                                                                    else "positional",
                                                                    call_site=site["site_id"],
                                                                    expression=ast.unparse(arg)),
                                               target_ids=sorted(a.target for a in supplied.atoms
                                                                 if a.kind in CALLABLE_KINDS),
                                               unknown_reasons=sorted(supplied.reasons)),
                                           "unknown" if supplied.unknown else "observed",
                                           producer_site=site["site_id"], consumer_site=use_site)
                    else:
                        default = self.parameter_default(t, param.arg)
                        if default is not None:
                            default_scope = self.nodes[scope]["parent"]
                            supplied = self.resolve(default_scope, default)
                            results.append(supplied)
                            use_site, use_expr = self._unit_consumer_in(scope, param)
                            self._unit_support(default_scope, default, scope, use_expr,
                                               "default-parameter", dict(
                                                   parameter=dict(name=param.arg, index=index,
                                                                  kind="default"),
                                                   argument_source=dict(kind="definition-time-default",
                                                                        expression=ast.unparse(default)),
                                                   target_ids=sorted(a.target for a in supplied.atoms
                                                                     if a.kind in CALLABLE_KINDS),
                                                   unknown_reasons=sorted(supplied.reasons)),
                                               "unknown" if supplied.unknown else "observed",
                                               consumer_site=use_site)
                        else:
                            results.append(unknown("missing-required-argument"))
                            use_site, use_expr = self._unit_consumer_in(scope, param)
                            self._unit_support(site["execution_owner"], call, scope, use_expr,
                                               "actual-parameter", dict(
                                                   parameter=dict(name=param.arg, index=index,
                                                                  kind="keyword-only" if param in t.args.kwonlyargs
                                                                  else "positional"),
                                                   argument_source=dict(kind="missing",
                                                                        call_site=site["site_id"],
                                                                        expression=ast.unparse(call)),
                                                   target_ids=[],
                                                   unknown_reasons=["missing-required-argument"]),
                                               "unknown", producer_site=site["site_id"],
                                               consumer_site=use_site)
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

    def container_slots(self, atom, scope, anchor, lookup, seen=None, coverage=None):
        """Read a finite literal/copy snapshot, with ordered writes and explicit coverage."""
        consumer = self.module_for[scope]
        self._record_analysis_dependency(
            self.analysis_watches, (consumer, "slot-writer-universe", "all-captured-python"))
        owner = self.stack[0][0] if self.stack else scope
        self.unit_analysis_watches.add((owner, consumer, "slot-writer-universe",
                                        "all-captured-python"))
        coverage = coverage if coverage is not None else EffectCoverage("container-state")
        seen = set() if seen is None else seen
        if atom.target in seen:
            coverage.gaps.append("recursive-dict-expansion")
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
                coverage.gaps.append("nonunique-instance-container-allocation")
                return {}, set(), [unknown("nonunique-instance-container-allocation")], events
        sequence = not isinstance(obj, ast.Dict)
        slots, sealed, extra = {}, set(), []

        def uncertain(reason, contributions=()):
            value = union(unknown(reason), *contributions)
            for k in list(slots):
                slots[k] = [union(*slots[k], value)]
            slots[_DYNAMIC] = [union(*slots.get(_DYNAMIC, []), value)]
            sealed.clear()

        if sequence:
            slots = {i: [self.resolve(owner, v)] for i, v in enumerate(obj.elts)}
            sealed = set(slots)
        else:
            overrides = (
                [
                    i
                    for i, k in enumerate(obj.keys)
                    if k is not None and self.literal_key(k) == (True, lookup)
                ]
                if lookup is not None
                else []
            )
            last_override = max(overrides, default=-1)
            for index, (key, value) in enumerate(zip(obj.keys, obj.values)):
                if key is not None:
                    literal_fixed, literal_value = self.literal_key(key)
                    address = key_identity(literal_value) if literal_fixed else None
                    self._unit_write(self._unit_origin(atom), "exact" if address is not None else "range",
                                     address, owner, key, "dictionary-literal",
                                     "observed" if address is not None else "unknown")
                if key is None:
                    if index < last_override:
                        # The queried key is definitely overwritten later in this literal.
                        continue
                    events.append(dict(kind="DictUnpack", scope=owner, line=value.lineno))
                    origins = self.resolve(owner, value)
                    coverage.source(
                        "dict-expansion-origin",
                        bool(origins.atoms)
                        and not origins.unknown
                        and self.requirements_complete(origins),
                    )
                    if origins.unknown or len(origins.atoms) != 1:
                        uncertain("unknown-or-ambiguous-dict-expansion")
                    for source in origins.atoms:
                        if source.kind != "container" or not isinstance(
                            self.container_exprs[source.target][1], ast.Dict
                        ):
                            uncertain("non-dictionary-expansion-source")
                            continue
                        values, source_sealed, limitations, nested = self.container_slots(
                            source, owner, value, lookup, seen, coverage
                        )
                        events.extend(nested)
                        if _DYNAMIC in values or limitations:
                            uncertain(
                                "incomplete-dict-expansion",
                                [*values.get(_DYNAMIC, []), *limitations],
                            )
                        for k, rs in values.items():
                            if k is _DYNAMIC:
                                continue
                            copied = union(*rs, *limitations)
                            maybe_missing = bool(limitations) or any(
                                a.kind == "possible-missing-slot" for a in copied.atoms
                            )
                            ambiguous = origins.unknown or len(origins.atoms) != 1
                            if maybe_missing or ambiguous:
                                prior = union(
                                    *slots.get(k, [known("possible-missing-slot", repr(k))])
                                )
                                copied = union(copied, prior)
                                if not any(a.kind == "possible-missing-slot" for a in prior.atoms):
                                    copied = Result(
                                        frozenset(
                                            a
                                            for a in copied.atoms
                                            if a.kind != "possible-missing-slot"
                                        ),
                                        copied.reasons,
                                        copied.proofs,
                                        copied.requirements,
                                    )
                            slots[k] = [copied]
                            # Presence/overwrite information is not permission to erase
                            # source uncertainty. Only an established finite value seals.
                            if (
                                k in source_sealed
                                and not copied.unknown
                                and not maybe_missing
                                and not ambiguous
                            ):
                                sealed.add(k)
                            else:
                                sealed.discard(k)
                else:
                    fixed, k = self.literal_key(key)
                    if fixed:
                        slots[k] = [self.resolve(owner, value)]
                        sealed.add(k)
                    else:
                        uncertain("dynamic-literal-dict-key")
        candidates = (self._slot_scopes_by_origin.get(atom.target, set()) |
                      self._slot_fallback_scopes | {scope, owner})
        self.slot_scope_candidates_checked += len(candidates)
        for function in sorted(candidates):
            root_owner = self.stack[0][0] if self.stack else scope
            self.unit_analysis_reads.add((root_owner, consumer, self.module_for[function],
                                          "container-effects"))
            self._record_analysis_dependency(
                self.analysis_reads, (consumer, self.module_for[function], "container-effects"))
            tree = self.trees[function]
            scoped_events = self.effects.before(function, anchor if function == scope else None)
            for event in scoped_events:
                self.slot_events_checked += 1
                statement = event.node
                coverage.require(event)
                coverage.record(
                    event,
                    EffectOutcome(
                        EffectKind.NO_EFFECT,
                        "no-container-dependency"
                        if event.reachable
                        else "unreachable-after-termination",
                    ),
                )
                if not event.reachable:
                    continue
                if event.kind in ("implicit-call", "region", "scope-execution"):
                    effect = implicit_execution_effect(event)
                    coverage.record(event, effect)
                    if effect.kind == EffectKind.UNKNOWN_EFFECT:
                        extra.append(unknown(effect.reason))
                if event.kind not in {
                    "write",
                    "call",
                    "await",
                    "region",
                    "terminate",
                    "binding",
                    "implicit-call",
                    "scope-execution",
                }:
                    coverage.record(
                        event, EffectOutcome(EffectKind.UNKNOWN_EFFECT, "missing-effect-handler")
                    )
                    extra.append(unknown("missing-effect-handler"))
                region_scope = (
                    self.owner[id(statement)] if event.kind == "scope-execution" else function
                )
                if event.kind in ("await", "region", "scope-execution") and any(
                    isinstance(n, ast.Name)
                    and isinstance(n.ctx, ast.Load)
                    and self.execution_nodes.get(id(n), (None,))[0] == region_scope
                    and self.container_reachable(function, n, atom)
                    for n in ast.walk(statement)
                ):
                    coverage.record(
                        event,
                        EffectOutcome(
                            EffectKind.UNKNOWN_EFFECT, "unsupported-related-container-region"
                        ),
                    )
                    extra.append(unknown("unsupported-related-container-region"))
                if not isinstance(
                    statement, (ast.Assign, ast.AnnAssign, ast.Delete, ast.AugAssign)
                ):
                    continue
                for dest in self.write_targets(statement):
                    if not isinstance(dest, ast.Subscript):
                        continue
                    owners = self.resolve(function, dest.value)
                    if atom not in owners.atoms:
                        if function in (scope, owner) and owners.unknown:
                            coverage.record(
                                event,
                                EffectOutcome(
                                    EffectKind.UNKNOWN_EFFECT, "unproven-slot-write-receiver"
                                ),
                            )
                            extra.append(unknown("unproven-slot-write-receiver"))
                        continue
                    events.append(
                        dict(kind=type(statement).__name__, scope=function, line=statement.lineno)
                    )
                    if isinstance(statement, ast.AnnAssign) and statement.value is None:
                        continue
                    write_fixed, key = self.literal_key(dest.slice)
                    address = key_identity(key) if write_fixed else None
                    self._unit_write(self._unit_origin(atom), "exact" if address is not None else "range",
                                     address, function, statement, type(statement).__name__,
                                     "candidate" if event.conditional or not event.ordered
                                     else "observed")
                    if sequence and write_fixed and isinstance(key, int) and key < 0:
                        key += len(slots)
                    direct = not event.conditional and event.ordered and function in (scope, owner)
                    relevant = sequence or lookup is None or not write_fixed or lookup == key
                    if not relevant:
                        continue
                    status = (
                        EffectKind.KNOWN_EFFECT
                        if direct and write_fixed and not isinstance(statement, ast.AugAssign)
                        else EffectKind.UNKNOWN_EFFECT
                    )
                    if isinstance(statement, ast.Delete):
                        if direct and write_fixed:
                            slots.pop(key, None)
                            sealed.add(key)
                            if sequence:
                                slots = {
                                    i: rs
                                    for i, rs in enumerate(rs for _, rs in sorted(slots.items()))
                                }
                        elif write_fixed:
                            prior = union(*slots.get(key, []))
                            slots[key] = [
                                union(
                                    prior,
                                    known("possible-missing-slot", repr(key)),
                                    unknown("conditional-or-dynamic-slot-deletion"),
                                )
                            ]
                            sealed.discard(key)
                        elif lookup is None or not write_fixed or lookup == key:
                            extra.append(unknown("conditional-or-dynamic-slot-deletion"))
                    elif isinstance(statement, ast.AugAssign):
                        extra.append(unknown("unsupported-slot-augassign"))
                    elif (
                        isinstance(dest.slice, ast.Name)
                        and isinstance(statement.value, ast.Name)
                        and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and function != scope
                    ):
                        associations = self.registry_arguments(
                            function, dest.slice.id, statement.value.id, lookup, atom.allocation
                        )
                        extra.extend(associations)
                        coverage.record(
                            event,
                            EffectOutcome(
                                EffectKind.UNKNOWN_EFFECT
                                if any(r.unknown for r in associations)
                                else EffectKind.KNOWN_EFFECT,
                                "registry-argument-association",
                            ),
                        )
                    elif direct and write_fixed:
                        slots[key] = [self.resolve(function, statement.value)]
                        sealed.add(key)
                    elif write_fixed:
                        prior = union(*slots.get(key, [known("possible-missing-slot", repr(key))]))
                        slots[key] = [
                            union(
                                prior,
                                self.resolve(function, statement.value),
                                unknown("conditional-or-dynamic-slot-write"),
                            )
                        ]
                        sealed.discard(key)
                    elif lookup is None or not write_fixed or key == lookup:
                        extra.extend(
                            [
                                self.resolve(function, statement.value),
                                unknown("conditional-or-dynamic-slot-write"),
                            ]
                        )
                    registry = (
                        isinstance(dest.slice, ast.Name)
                        and isinstance(getattr(statement, "value", None), ast.Name)
                        and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and function != scope
                        and not isinstance(statement, (ast.Delete, ast.AugAssign))
                    )
                    if not registry:
                        coverage.record(
                            event,
                            EffectOutcome(
                                status,
                                "ordered-slot-update"
                                if status == EffectKind.KNOWN_EFFECT
                                else "conditional-or-unsupported-slot-update",
                            ),
                        )
            for event in scoped_events:
                if event.kind != "call" or not event.reachable:
                    continue
                call, callee = event.node, event.node.func
                uses = (
                    ([callee.value] if isinstance(callee, ast.Attribute) else [])
                    + call.args
                    + [kw.value for kw in call.keywords]
                )
                if any(self.container_reachable(function, use, atom) for use in uses):
                    events.append(dict(kind="container-escape", scope=function, line=call.lineno))
                    extra.append(unknown("container-mutation-or-escape"))
                    coverage.record(
                        event,
                        EffectOutcome(EffectKind.UNKNOWN_EFFECT, "container-mutation-or-escape"),
                    )
        return slots, sealed, extra, events

    def subscript(self, scope, expr):
        """Resolve a slot only after the relevant ordered writes and sources are covered."""
        containers = self.resolve(scope, expr.value)
        fixed, key = self.literal_key(expr.slice)
        results, events = [], []
        cov = EffectCoverage("container-write-source-coverage")
        cov.source(
            "finite-container-origin",
            bool(containers.atoms)
            and not containers.unknown
            and all(a.kind == "container" for a in containers.atoms)
            and self.requirements_complete(containers),
        )
        for atom in containers.atoms:
            if atom.kind != "container":
                continue
            slots, sealed, extra, observed = self.container_slots(
                atom, scope, expr, key if fixed else None, coverage=cov
            )
            address = key_identity(key) if fixed else None
            self._unit_subscribe(self._unit_origin(atom), "exact" if address is not None else "range",
                                 address, scope, expr, containers.reasons)
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
            for candidate in chosen:
                cov.source(
                    "selected-literal-slot-value",
                    bool(candidate.proofs)
                    and not candidate.unknown
                    and self.requirements_complete(candidate),
                )
            results.append(
                certified(union(*chosen, *extra), "literal-slot-state")
                if chosen or extra
                else invalid("missing-literal-slot")
            )
        if containers.unknown:
            self._unit_subscribe("unknown-container-universe", "range", None,
                                 scope, expr, containers.reasons)
            results.append(unknown("unknown-container-origin"))
        result = union(*results) if results else unknown("unresolved-container-slot")
        cov.events.extend(events)
        self.coverage[(scope, id(expr))] = cov.export()
        # Private evidence is recorded at the actual resolver read. Source spans,
        # rather than transient AST object addresses, are exported by Graph.
        if isinstance(expr.slice, ast.Constant) and type(expr.slice.value) is str:
            self.value_reads[(scope, expr.lineno, expr.col_offset)] = result
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
        for site in self.candidate_sites(function):
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
        self._observe_analysis_input(owner, "member-lookup")
        self._record_scope_read(owner, "member-lookup")
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
        self._observe_analysis_input(function, "call-candidates",
                                     producer_scope=site["execution_owner"],
                                     consumer_scope=function)
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
        def source_order(key):
            record = self.traces.get(key, {})
            before = key[2] if isinstance(key[2], tuple) else (key[2], 0)
            return (record.get("scope", key[0]), record.get("path", ""),
                    record.get("line", before[0]), record.get("column", before[1]),
                    record.get("expression", ""), record.get("rule", ""),
                    canonical(record) if record else "")
        while pending and len(steps) < 100:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            if key in self.traces:
                steps.append(self.traces[key])
            # Independent association branches can be visited in different
            # memo/Jedi orders. Sort siblings by captured source coordinates so
            # full and updated builds export the same bounded provenance order.
            pending.extend(reversed(sorted(self.dependencies.get(key, []), key=source_order)))
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

    def coverage_receipt(self, scope, expr, result):
        """Combine explicit source obligations, including those inherited through aliases."""
        keys = set(result.requirements)
        if (scope, id(expr)) in self.coverage and isinstance(expr, (ast.Attribute, ast.Subscript)):
            if not (
                result.atoms and all(a.kind in ("boundary", "external-value") for a in result.atoms)
            ):
                keys.add((scope, id(expr)))
        if not keys:
            return None
        receipts = [self.coverage.get(k) for k in keys]
        if len(receipts) == 1 and receipts[0] is not None:
            return receipts[0]
        return dict(
            rule="transitive-write-source-coverage",
            complete=all(valid_coverage(r) for r in receipts),
            events=[e for r in receipts if r for e in r["events"]],
            dependencies=[
                r if r else dict(complete=False, gaps=["missing-coverage"]) for r in receipts
            ],
        )

    def complete(self, result):
        """Public completeness requires both source proof and all effect obligations."""
        return bool(result.proofs) and not result.unknown and self.requirements_complete(result)

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
        receipt = self.coverage_receipt(scope, expr, result)
        derived_rules = {
            "literal-slot-state",
            "python-instance-field-precedence",
            "python-nondata-member-lookup",
        }
        needs_coverage = bool(result.requirements or result.proofs & derived_rules) or (
            isinstance(expr, ast.Subscript) or isinstance(expr, ast.Attribute) and bool(chosen)
        )
        if needs_coverage and not valid_coverage(receipt) and not result.unknown:
            result = union(result, unknown("missing-write-source-coverage"))
        justified = bool(result.proofs & decisive)
        if needs_coverage:
            justified = valid_coverage(receipt)
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
