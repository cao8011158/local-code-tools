"""Captured-source Jedi observations and AST site inventory.

Only Jedi supplies semantic targets. The source recorder stores dependency
positions without evaluating a Python value or deciding call targets.
"""

import ast
import io
import sys
import tempfile
import tokenize
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import jedi

from .analysis_inputs import AnalysisInputs
from .common import canonical, digest
from .parso_cache_compat import ensure_parso_cache_timestamps
from .source_recorder import SourceRecorder

ANALYSIS_DEPENDENCY_LIMIT = 20000
ANALYSIS_READ_KINDS = frozenset({"container-effects", "member-lookup", "return-body",
                                 "parameter-origin", "jedi-target"})
CALLABLE_KINDS = frozenset({"callable", "class"})


class RequiredAnalysisContext(Exception):
    def __init__(self, repository, path):
        self.repository, self.path = repository, path
        super().__init__(repository, path)


@dataclass(frozen=True)
class Atom:
    kind: str
    target: str


@dataclass(frozen=True)
class Result:
    atoms: frozenset = frozenset()
    reasons: frozenset = frozenset()

    @property
    def unknown(self):
        return bool(self.reasons)


class Analyzer:
    """One capture's site inventory and direct Jedi query bridge."""

    def __init__(self, nodes, trees, repos, imported, source_context=None,
                 candidate_site_evidence=None, selected_owners=None):
        ensure_parso_cache_timestamps()
        self.nodes, self.trees, self.repos, self.imported = nodes, trees, repos, imported
        self.owner = {id(t): ident for ident, t in trees.items()}
        self.modules = {i: t for i, t in trees.items() if isinstance(t, ast.Module)}
        self.temp = tempfile.TemporaryDirectory(prefix="lct-python-")
        self.root = Path(self.temp.name)
        self.paths, self.scripts, self.module_for = {}, {}, {}
        self.sites, self.references, self.import_sites, self.inheritance = [], [], [], []
        self.context_sites, self.execution_nodes = [], {}
        self.queries, self._raw_jedi_observations = {}, {}
        self.reused_queries = self.executed_queries = self.query_entries = 0
        self.query_cache_hits = self.raw_jedi_observation_hits = 0
        self.site_queries_prepared = 0
        self.raw_query_counts = defaultdict(int)
        self.analysis_inputs = AnalysisInputs({i: n for i, n in nodes.items()
                                              if n["kind"] == "module"})
        context = (source_context if source_context is not None else
                   {i: t._lct_source for i, t in self.modules.items()})
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
        library_paths = [p for p in sys.path if p and
                         ("site-packages" in p or "python" in p.lower()) and
                         str(Path(p).resolve()) != str(Path.cwd().resolve())]
        projects = {}
        for repository in roots:
            dependencies = set()
            for ident in context:
                module = nodes[ident]
                if module["repository"] != repository and ident in imported(
                        repository, module["qualname"]):
                    dependencies.update(roots[module["repository"]])
            projects[repository] = jedi.Project(
                self.root / repository,
                sys_path=sorted(roots[repository]) + sorted(dependencies - roots[repository])
                + library_paths, smart_sys_path=False, load_unsafe_extensions=False)
        for path, ident in self.paths.items():
            if ident in self.modules:
                self.scripts[ident] = jedi.Script(
                    code=trees[ident]._lct_source, path=path,
                    project=projects[nodes[ident]["repository"]])
        for ident in trees:
            mod = ident
            while nodes[mod]["kind"] != "module":
                mod = nodes[mod]["parent"]
            self.module_for[ident] = mod
        self._source_lines = {i: t._lct_source.splitlines() for i, t in self.modules.items()}
        self._call_parentheses = {}
        self._definitions_by_line = defaultdict(list)
        for ident, node in nodes.items():
            if ident in self.module_for:
                self._definitions_by_line[self.module_for[ident], node["definition_line"]].append(ident)
        for ident, tree in self.modules.items():
            deferred = any(isinstance(s, ast.ImportFrom) and s.module == "__future__"
                           and any(a.name == "annotations" for a in s.names)
                           for s in tree.body)
            self.inventory(tree, ident, ident, "module", deferred)
        self.recorder = SourceRecorder(self, selected_owners)
        self.recorder.prepare()

    def inventory(self, obj, lexical, execution, phase, deferred):
        self.execution_nodes[id(obj)] = (execution, phase)
        if id(obj) in self.owner and not isinstance(obj, ast.Module):
            ident = self.owner[id(obj)]
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in obj.decorator_list:
                    self.inventory(d, ident, execution, "definition", deferred)
                    self.sites.append(self.site(d, ident, execution, "definition", "implicit_decorator"))
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
        n = self.nodes[self.module_for[execution]]
        key = [n["repository"], n["path"], n["snapshot_id"], expr.lineno,
               expr.col_offset, expr.end_lineno, expr.end_col_offset, kind]
        return dict(site_id=digest(canonical(key)), lexical_owner=lexical,
                    execution_owner=execution, phase=phase, kind=kind,
                    line=expr.lineno, column=expr.col_offset, end_line=expr.end_lineno,
                    end_column=expr.end_col_offset, expression=ast.unparse(expr),
                    _expr=expr, _call=call)

    def map_name(self, name):
        """Map only a Jedi declaration token; never evaluate an assignment RHS."""
        raw = dict(name=name.name, full_name=name.full_name, type=name.type,
                   line=name.line, column=name.column,
                   module_path=str(name.module_path) if name.module_path else None)
        module = self.paths.get(Path(name.module_path).resolve()) if name.module_path else None
        if module is not None and module not in self.modules:
            n = self.nodes[module]
            raise RequiredAnalysisContext(n["repository"], n["path"])
        if module is None:
            if not name.module_path and not name.full_name:
                raw["mapping"] = "unlocatable-jedi-result"
                return Result(reasons=frozenset({"unlocatable-jedi-result"})), raw
            raw["mapping"] = "external-or-excluded"
            return Result(frozenset({Atom("boundary", name.full_name or name.name)})), raw
        raw["module_path"] = self.nodes[module]["repository"] + "/" + self.nodes[module]["path"]
        raw["source_sha256"] = self.nodes[module]["source_sha256"]
        if name.type == "module":
            raw["mapping"] = "exact-captured-module"
            return Result(frozenset({Atom("module", module)})), raw
        lines = self._source_lines[module]
        col = len(lines[name.line - 1][:name.column].encode("utf-8")) if name.line else None
        matches = []
        for ident in self._definitions_by_line.get((module, name.line), ()):
            node, obj = self.nodes[ident], self.trees.get(ident)
            if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                prefix = ("async def " if isinstance(obj, ast.AsyncFunctionDef) else
                          "def " if isinstance(obj, ast.FunctionDef) else "class ")
                if node["name"] == name.name and obj.col_offset + len(prefix) == col and \
                        name.type in ("function", "class"):
                    matches.append(ident)
            elif isinstance(obj, ast.Lambda) and col == obj.col_offset:
                matches.append(ident)
        if len(matches) != 1:
            raw["mapping"] = ("unmapped-captured-binding" if name.type == "statement" else
                              "ambiguous-captured-definition" if matches else
                              "unmapped-captured-definition")
            raw["binding_location"] = [module, name.line, col]
            return Result(reasons=frozenset({raw["mapping"]})), raw
        target = matches[0]
        raw.update(mapping="exact-captured-definition", target=target,
                   version_id=self.nodes[target]["version_id"],
                   repository=self.nodes[module]["repository"])
        kind = "class" if self.nodes[target]["kind"] == "class" else "callable"
        return Result(frozenset({Atom(kind, target)})), raw

    def signature_position(self, call):
        """Locate the call's opening parenthesis through Python tokens."""
        module = self.module_for[self.execution_nodes[id(call)][0]]
        if module not in self._call_parentheses:
            source = self.modules[module]._lct_source
            parentheses = []
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.OP and token.string == "(":
                    line = self._source_lines[module][token.start[0] - 1]
                    byte = len(line[:token.start[1]].encode("utf-8"))
                    parentheses.append(((token.start[0], byte),
                                         (token.start[0], token.start[1] + 1)))
            self._call_parentheses[module] = parentheses
        start = call.func.end_lineno, call.func.end_col_offset
        end = call.end_lineno, call.end_col_offset
        parentheses = self._call_parentheses[module]
        index = bisect_left(parentheses, (start, (0, 0)))
        if index < len(parentheses) and parentheses[index][0] < end:
            return parentheses[index][1]
        return None

    def query(self, scope, expr, goto=False, signature=False):
        self.query_entries += 1
        module = self.module_for[scope]
        if signature:
            position = self.signature_position(expr)
            if position is None:
                return Result(reasons=frozenset({"call-parenthesis-unlocatable"}))
            line_number, column = position
            key = (module, line_number, column, "signature")
        else:
            key = (module, expr.end_lineno, expr.end_col_offset, goto)
        self.recorder.observe_query(scope, expr)
        if key in self.queries:
            self.query_cache_hits += 1
            return self.queries[key][0]
        if not signature:
            line_number = expr.end_lineno
            line = self._source_lines[module][line_number - 1]
            column = len(line.encode("utf-8")[:expr.end_col_offset].decode("utf-8"))
        observed = self._raw_jedi_observations.get(key)
        if observed is None:
            try:
                operation = (self.scripts[module].get_signatures if signature else
                             self.scripts[module].goto if goto else self.scripts[module].infer)
                names = operation(line_number, column)
                observed = names, None
            except Exception as exc:
                observed = (), type(exc).__name__
            self._raw_jedi_observations[key] = observed
            self.executed_queries += 1
        else:
            self.raw_jedi_observation_hits += 1
        names, error = observed
        raw, atoms, reasons = [], set(), set()
        if error:
            raw.append(dict(error=error, mapping="jedi-error"))
            reasons.add("jedi-error:" + error)
        for name in names:
            try:
                mapped, record = self.map_name(name)
            except Exception as exc:
                failure = type(exc).__name__
                raw.append(dict(error=failure, mapping="jedi-result-error"))
                reasons.add("jedi-result-error:" + failure)
                continue
            if signature:
                parameters = []
                try:
                    for p in name.params:
                        path = self.paths.get(Path(p.module_path).resolve()) if p.module_path else None
                        stable_path = (self.nodes[path]["repository"] + "/" + self.nodes[path]["path"]
                                       if path is not None else
                                       str(p.module_path) if p.module_path else None)
                        parameters.append(dict(name=p.name, kind=str(p.kind), line=p.line,
                                               column=p.column, module_path=stable_path))
                except Exception as exc:
                    # Signature parameter positions are source provenance,
                    # not the callable target. Preserve an already mapped
                    # Jedi target and expose this source-data failure.
                    record["parameters_error"] = type(exc).__name__
                    parameters = []
                record["parameters"] = parameters
            if record.get("target") and record.get("repository") != self.nodes[module]["repository"]:
                target_mod = self.nodes[self.module_for[record["target"]]]["qualname"]
                if self.module_for[record["target"]] not in self.imported(
                        self.nodes[module]["repository"], target_mod):
                    mapped = Result(frozenset({Atom("boundary", "dependency-version-unmatched:" + target_mod)}))
                    record["mapping"] = "dependency-version-unmatched"
            raw.append(record)
            atoms.update(mapped.atoms)
            reasons.update(mapped.reasons)
        if not names and not error:
            reasons.add("jedi-no-result")
        result = Result(frozenset(atoms), frozenset(reasons))
        self.queries[key] = result, raw
        for row in raw:
            self.raw_query_counts[row.get("mapping", "unmapped")] += 1
        if not raw:
            self.raw_query_counts["empty"] += 1
        return result

    def prepare_site_queries(self, owners=None):
        allowed = None if owners is None else set(owners)
        for site in self.sites:
            if site["_call"] is not None and (allowed is None or site["execution_owner"] in allowed):
                self.query(site["execution_owner"], site["_call"], signature=True)
                self.site_queries_prepared += 1

    def close(self):
        self.temp.cleanup()
