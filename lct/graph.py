"""Python relationships from the unified catalog, AST sites and mapped Jedi evidence."""

import ast
import tomllib
from collections import defaultdict
from pathlib import Path

from .common import ToolError, canonical, digest, git
from .python_analysis import CALLABLE_KINDS, Analyzer


class Graph:
    """Compatibility facade; site completeness is explicit, never fixed-point cardinality."""

    def __init__(self, nodes, asts, repos):
        self.nodes = {n["node_id"]: n for n in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("Node identity collision")
        self.asts = asts
        self.repos = {r["name"]: r for r in repos}
        self.modules = defaultdict(set)
        self.cross_bindings = {}
        self.edges = []
        for n in nodes:
            if n["kind"] == "module":
                self.modules[n["repository"], n["qualname"]].add(n["node_id"])
        for repo in repos:
            p = Path(repo["path"]) / "pyproject.toml"
            if p.exists():
                data = tomllib.loads(p.read_text(encoding="utf-8-sig"))
                sources = data.get("tool", {}).get("uv", {}).get("sources", {})
                for name, value in sources.items():
                    if isinstance(value, dict) and "trpg-rules-engine" in value.get("git", ""):
                        pin = value.get("rev")
                        target = self.repos.get("trpg-rules-engine", {})
                        clean = None
                        if pin == target.get("head") and pin:
                            try:
                                clean = not bool(
                                    git(
                                        target["path"],
                                        "status",
                                        "--porcelain",
                                        "--untracked-files=all",
                                        "--",
                                        "*.py",
                                    )
                                )
                            except (ToolError, KeyError):
                                clean = False
                        record = {
                            "pin": pin,
                            "target_head": target.get("head"),
                            "matched": pin == target.get("head") and clean is True,
                            "worktree_python_clean": clean,
                            "dependency": name,
                        }
                        group = self.cross_bindings.setdefault(repo["name"], {"dependencies": {}})
                        group["dependencies"][name] = record
                        group["matched"] = all(r["matched"] for r in group["dependencies"].values())
                        pins = {r["pin"] for r in group["dependencies"].values()}
                        group["pin"] = next(iter(pins)) if len(pins) == 1 else None
                        group["target_head"] = target.get("head")

    def imported(self, repo, name):
        """Cross-repository targets require the exact dependency revision to match."""
        local = self.modules.get((repo, name), set())
        if local:
            return set(local)
        if name.startswith(("dnd5e_engine", "dnd5e_srd_data")):
            dependency = "dnd5e-engine" if name.startswith("dnd5e_engine") else "dnd5e-srd-data"
            binding = self.cross_bindings.get(repo, {}).get("dependencies", {}).get(dependency, {})
            if binding.get("matched"):
                return set(self.modules.get(("trpg-rules-engine", name), set()))
            if repo != "trpg-rules-engine":
                return {"boundary:dependency-version-unmatched:" + name}
        return {"boundary:external-or-excluded:" + name}

    def add_edge(
        self, source, target, kind, status, basis, line=0, column=0, expression="", **extra
    ):
        """Store typed relations; CALLS edges are projections of a particular site."""
        edge = dict(
            source=source,
            target=target,
            kind=kind,
            status=status,
            basis=basis,
            line=line,
            column=column,
            expression=expression,
            **extra,
        )
        edge["source_version_id"] = self.nodes.get(source, {}).get("version_id")
        edge["target_version_id"] = self.nodes.get(target, {}).get("version_id")
        edge["edge_id"] = digest(canonical(edge))
        self.edges.append(edge)

    def build(self):
        """Analyze captured bytes only; return edges plus the independent site inventory."""
        self.edges = []
        for n in self.nodes.values():
            if n["parent"]:
                self.add_edge(
                    n["parent"],
                    n["node_id"],
                    "CONTAINS",
                    "resolved",
                    "AST lexical ownership",
                    n["start"],
                    n.get("column", 0),
                )
        analyzer = Analyzer(self.nodes, self.asts, self.repos, self.imported)
        try:
            sites = []
            for item in analyzer.sites:
                expr, scope = item["_expr"], item["execution_owner"]
                # Always retain the actual Jedi observation, including rejected descriptors.
                signal = analyzer.query(scope, expr)
                result = analyzer.resolve(scope, expr)
                if item["kind"] == "implicit_decorator" and isinstance(expr, ast.Call):
                    # Factory application calls its returned decorator, not the factory again.
                    result = analyzer.resolve(scope, expr)
                result, decision = analyzer.adjudicate(scope, expr, result, signal)
                targets = sorted({a.target for a in result.atoms if a.kind in CALLABLE_KINDS})
                boundaries = sorted({a.target for a in result.atoms if a.kind == "boundary"})
                reasons = sorted(result.reasons)
                if any(b.startswith("dependency-version-unmatched:") for b in boundaries):
                    reasons.append("dependency-version-unmatched")
                complete = not reasons and bool(result.proofs)
                record = {k: v for k, v in item.items() if not k.startswith("_")}
                record.update(
                    targets=targets,
                    unknown_origin=bool(reasons),
                    complete=complete,
                    completeness_basis=sorted(result.proofs) if complete else None,
                    resolution_kind=(
                        "proven-targets" if targets or boundaries else "proven-no-target"
                    )
                    if complete
                    else ("partial-targets" if targets or boundaries else "unsupported-or-unknown"),
                    resolution_decision=decision,
                    unresolved_reasons=reasons,
                    boundaries=[
                        dict(
                            full_name=b,
                            reason="dependency-version-unmatched"
                            if b.startswith("dependency-version-unmatched:")
                            else "external-or-excluded",
                        )
                        for b in boundaries
                    ],
                    evidence=[
                        dict(tool="ast", role="site and execution phase"),
                        dict(
                            tool="jedi",
                            version="0.20.1",
                            role="definition signal",
                            raw=analyzer.queries[
                                (
                                    analyzer.module_for[scope],
                                    expr.end_lineno,
                                    expr.end_col_offset,
                                    False,
                                )
                            ][1],
                        ),
                        dict(
                            tool="lct",
                            role="validated binding/argument/container association",
                            association_trace=analyzer.explain(scope, expr),
                            decision=decision,
                            signal_agrees=targets
                            == sorted(a.target for a in signal.atoms if a.kind in CALLABLE_KINDS),
                        ),
                    ],
                )
                sites.append(record)
                status = (
                    "resolved" if complete and len(targets) + len(boundaries) == 1 else "possible"
                )
                for target in targets:
                    self.add_edge(
                        scope,
                        target,
                        "CALLS",
                        status,
                        "mapped AST/Jedi/LCT site",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                        target_role="decorated-factory"
                        if any(
                            a.target == target
                            and a.kind in ("context-factory", "async-context-factory")
                            for a in result.atoms
                        )
                        else "definition",
                        invocation_phase="context-manager-create"
                        if any(
                            a.target == target
                            and a.kind in ("context-factory", "async-context-factory")
                            for a in result.atoms
                        )
                        else "ordinary-call",
                        executes_body=False
                        if any(
                            a.target == target
                            and a.kind in ("context-factory", "async-context-factory")
                            for a in result.atoms
                        )
                        else None,
                    )
                for boundary in boundaries:
                    target = "boundary:" + (
                        "dependency-version-unmatched:" + boundary.split(":", 1)[1]
                        if boundary.startswith("dependency-version-unmatched:")
                        else "external-or-excluded:" + boundary
                    )
                    self.add_edge(
                        scope,
                        target,
                        "CALLS",
                        "boundary",
                        "captured source boundary",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                    )
                if not targets and not boundaries:
                    self.add_edge(
                        scope,
                        None,
                        "CALLS",
                        "unresolved",
                        "; ".join(reasons) or "invalid/noncallable target",
                        item["line"],
                        item["column"],
                        item["expression"],
                        site_id=item["site_id"],
                        complete=complete,
                        unknown_origin=bool(reasons),
                    )
            for ident, tree in self.asts.items():
                if (
                    not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or len(tree.decorator_list) != 1
                ):
                    continue
                wrapper = analyzer.context_wrapper(
                    self.nodes[ident]["parent"], tree.decorator_list[0]
                )
                if wrapper:
                    origin = (
                        "contextlib.asynccontextmanager"
                        if wrapper == "async-context-factory"
                        else "contextlib.contextmanager"
                    )
                    self.add_edge(
                        "boundary:external-or-excluded:" + origin,
                        ident,
                        "WRAPS",
                        "resolved",
                        "verified contextlib decorator binds a generator factory",
                        tree.lineno,
                        tree.col_offset,
                        wrapper_origin=origin,
                        wrapped_body_phase="generator-resume",
                    )
            for scope, statement, context in analyzer.context_sites:
                receivers = analyzer.resolve(scope, context)
                expected = (
                    "async-context-manager"
                    if isinstance(statement, ast.AsyncWith)
                    else "context-manager"
                )
                for receiver in receivers.atoms:
                    if receiver.kind != expected:
                        continue
                    self.add_edge(
                        scope,
                        receiver.target,
                        "CONTEXT_ENTERS",
                        "possible" if receivers.unknown else "resolved",
                        "context entry resumes the wrapped generator, separate from factory creation",
                        context.lineno,
                        context.col_offset,
                        ast.unparse(context),
                        invocation_phase="generator-resume",
                        executes_body=True,
                        complete=not receivers.unknown,
                        unknown_origin=receivers.unknown,
                    )
            for scope, expr, phase in analyzer.references:
                result = analyzer.resolve(scope, expr)
                for a in result.atoms:
                    if a.kind in CALLABLE_KINDS or a.kind == "module":
                        self.add_edge(
                            scope,
                            a.target,
                            "REFERENCES",
                            "possible" if result.unknown else "resolved",
                            "AST value reference; never implies invocation",
                            expr.lineno,
                            expr.col_offset,
                            ast.unparse(expr),
                            phase=phase,
                        )
            for scope, stmt in analyzer.import_sites:
                for alias in stmt.names:
                    result = analyzer.binding(scope, "import", (stmt, alias))
                    for a in result.atoms:
                        external = a.kind in ("boundary", "external-module", "external-value")
                        target = a.target
                        if external:
                            target = "boundary:" + (
                                a.target
                                if a.target.startswith("dependency-version-unmatched:")
                                else "external-or-excluded:" + a.target
                            )
                        self.add_edge(
                            scope,
                            target,
                            "IMPORTS",
                            "boundary" if external else "resolved",
                            "exact captured import definition",
                            stmt.lineno,
                            stmt.col_offset,
                            alias.name,
                        )
                    if not result.atoms:
                        self.add_edge(
                            scope,
                            None,
                            "IMPORTS",
                            "unresolved",
                            "; ".join(sorted(result.reasons)),
                            stmt.lineno,
                            stmt.col_offset,
                            alias.name,
                        )
            for ident, scope, base in analyzer.inheritance:
                result = analyzer.resolve(scope, base)
                for a in result.atoms:
                    if a.kind == "class":
                        self.add_edge(
                            ident,
                            a.target,
                            "INHERITS",
                            "resolved",
                            "explicit AST base",
                            base.lineno,
                            base.col_offset,
                            ast.unparse(base),
                        )
            self.edges = list({e["edge_id"]: e for e in self.edges}.values())
            return self.edges, dict(
                engine="AST catalog + Jedi 0.20.1 + finite LCT associations",
                schema=3,
                sites=sites,
                call_sites=len(sites),
                analysis_limited=analyzer.limited,
                association_evaluations=20000 - analyzer.budget,
                jedi_queries=len(analyzer.queries),
                dependency_bindings=self.cross_bindings,
                closed_world={k: bool(r.get("closed_world", False)) for k, r in self.repos.items()},
                limits="20k associations; recursion 40; unsupported constructs remain unknown",
            )
        finally:
            analyzer.close()
