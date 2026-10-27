"""Snapshot-local execution events and independent effect coverage receipts.

This inventory observes syntax, never executes it. Conditional/unordered regions are
kept even when no effect handler supports them; deferred bodies have their own scope.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum


class EffectKind(str, Enum):
    """Every inspected event has an explicit semantic disposition."""

    NO_EFFECT = "NO_EFFECT"
    KNOWN_EFFECT = "KNOWN_EFFECT"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"


@dataclass(frozen=True)
class EffectOutcome:
    """An effect plus its applicability reason; None is never an outcome."""

    kind: EffectKind
    reason: str
    value: object = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EffectEvent:
    """An operation after its operands, within one execution scope."""

    scope: str
    node: ast.AST
    kind: str
    order: int
    conditional: bool
    ordered: bool
    reachable: bool
    phase: str

    @property
    def ident(self):
        """Snapshot-local stable scope/order key, independent of memory addresses."""
        return f"{self.scope}:{self.order}:{self.kind}"

    def location(self):
        """Export public evidence without the internal AST object."""
        return dict(
            event_id=self.ident,
            kind=self.kind,
            syntax=type(self.node).__name__,
            scope=self.scope,
            line=self.node.lineno,
            column=self.node.col_offset,
            conditional=self.conditional,
            ordered=self.ordered,
            reachable=self.reachable,
            phase=self.phase,
        )


class EffectCatalog:
    """Build once from AST inventory ownership, with bounded syntactic ordering.

    Branches are alternatives, not a claimed runtime path. Loops, exception and
    suspension protocols retain explicit regions rather than inventing CFG edges.
    """

    def __init__(self, trees, ownership):
        self.by_scope, self.points = {}, {}
        self.ownership = ownership
        for scope, tree in trees.items():
            self.by_scope[scope] = []
            self.clock = 0
            parts = [tree.body] if isinstance(tree, ast.Lambda) else tree.body
            self.block(parts, scope, False, True, True)

        self.slot_scopes = {
            scope
            for scope, events in self.by_scope.items()
            if any(
                e.kind == "write"
                and any(
                    isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del))
                    for n in ast.walk(e.node)
                )
                for e in events
            )
        }

    def block(self, parts, scope, conditional, ordered, reachable):
        """Only unconditional straight-line terminators prove subsequent unreachability."""
        for node in parts:
            self.visit(node, scope, conditional, ordered, reachable)
            if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                reachable = False

    def visit(self, node, scope, conditional=False, ordered=True, reachable=True):
        if node is None:
            return
        meta = self.ownership.get(id(node))
        if meta and meta[0] != scope:
            return
        phase = meta[1] if meta else "body"
        if isinstance(
            node,
            (
                ast.For,
                ast.AsyncFor,
                ast.With,
                ast.AsyncWith,
                ast.ExceptHandler,
                ast.MatchAs,
                ast.MatchStar,
                ast.MatchMapping,
            ),
        ):
            # These constructs can bind names before a nested body. Their protocols/order
            # are unsupported, so do not specialize a rebound receiver in that body.
            self.add(scope, node, "binding", True, False, reachable, phase)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            # Only definition-time expressions here; body has an independent inventory.
            children = list(getattr(node, "decorator_list", []))
            if isinstance(node, ast.ClassDef):
                children += node.bases + [k.value for k in node.keywords]
            else:
                children += node.args.defaults + [x for x in node.args.kw_defaults if x]
                children += [
                    a.annotation
                    for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                    if a.annotation
                ]
                children += [
                    x.annotation for x in (node.args.vararg, node.args.kwarg) if x and x.annotation
                ]
                if getattr(node, "returns", None):
                    children.append(node.returns)
            for child in children:
                if id(child) in self.ownership:
                    self.visit(child, scope, conditional, ordered, reachable)
            if isinstance(node, ast.ClassDef):
                self.add(
                    scope, node, "scope-execution", conditional, False, reachable, "definition"
                )
            for decorator in reversed(getattr(node, "decorator_list", [])):
                self.add(
                    scope, decorator, "implicit-call", conditional, ordered, reachable, "definition"
                )
            if not isinstance(node, ast.Lambda):
                self.add(scope, node, "binding", conditional, ordered, reachable, phase)
        elif isinstance(node, ast.If):
            self.visit(node.test, scope, conditional, ordered, reachable)
            self.block(node.body, scope, True, ordered, reachable)
            self.block(node.orelse, scope, True, ordered, reachable)
        elif isinstance(node, ast.IfExp):
            self.visit(node.test, scope, conditional, ordered, reachable)
            self.visit(node.body, scope, True, ordered, reachable)
            self.visit(node.orelse, scope, True, ordered, reachable)
        elif isinstance(node, ast.Compare):
            self.visit(node.left, scope, conditional, ordered, reachable)
            for i, child in enumerate(node.comparators):
                self.visit(child, scope, conditional or i > 0, ordered, reachable)
        elif isinstance(node, ast.BoolOp):
            for i, child in enumerate(node.values):
                self.visit(child, scope, conditional or i > 0, ordered, reachable)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            self.visit(node.value, scope, conditional, ordered, reachable)
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                self.visit(target, scope, conditional, ordered, reachable)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                self.visit(key, scope, conditional, ordered, reachable)
                self.visit(value, scope, conditional, ordered, reachable)
        else:
            unsupported = isinstance(
                node,
                (
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.Try,
                    ast.TryStar,
                    ast.With,
                    ast.AsyncWith,
                    ast.Match,
                    ast.ListComp,
                    ast.SetComp,
                    ast.DictComp,
                    ast.GeneratorExp,
                    ast.Yield,
                    ast.YieldFrom,
                    ast.Assert,
                ),
            )
            for child in ast.iter_child_nodes(node):
                self.visit(
                    child, scope, conditional or unsupported, ordered and not unsupported, reachable
                )
            if unsupported:
                self.add(scope, node, "region", conditional, False, reachable, phase)
        self.clock += 1
        self.points[(scope, id(node))] = self.clock
        kind = (
            "call"
            if isinstance(node, ast.Call)
            else "await"
            if isinstance(node, ast.Await)
            else "write"
            if isinstance(
                node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete, ast.NamedExpr)
            )
            else "terminate"
            if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue))
            else "binding"
            if isinstance(node, (ast.Import, ast.ImportFrom))
            else None
        )
        if kind:
            self.add(scope, node, kind, conditional, ordered, reachable, phase)

    def add(self, scope, node, kind, conditional, ordered, reachable, phase):
        """Register an operation regardless of available semantic handlers."""
        self.clock += 1
        self.by_scope[scope].append(
            EffectEvent(scope, node, kind, self.clock, conditional, ordered, reachable, phase)
        )

    def before(self, scope, anchor=None):
        """Read a precomputed scope prefix; never scan another AST or the repository."""
        limit = self.points.get((scope, id(anchor)), float("inf"))
        return [e for e in self.by_scope.get(scope, []) if e.order < limit]


def valid_coverage(receipt):
    """Validate obligations, never accept a bare complete flag or semantic label."""
    if not receipt or receipt.get("complete") is not True:
        return False
    if "dependencies" in receipt:
        return bool(receipt["dependencies"]) and all(
            valid_coverage(r) for r in receipt["dependencies"]
        )
    required = receipt.get("required_events")
    checks, sources = receipt.get("checks", []), receipt.get("sources", [])
    if required is None or not sources or receipt.get("gaps"):
        return False
    ids = [c.get("event_id") for c in checks]
    return (
        len(ids) == len(set(ids))
        and set(ids) == set(required)
        and all(
            c.get("outcome") in (EffectKind.NO_EFFECT.value, EffectKind.KNOWN_EFFECT.value)
            for c in checks
        )
        and all(s.get("supported") is True for s in sources)
    )


class EffectCoverage:
    """Required operations, dispositions and source obligations, independently checked."""

    def __init__(self, rule):
        self.rule, self.required, self.outcomes = rule, {}, {}
        self.events, self.sources, self.gaps = [], [], []

    def require(self, event):
        """Declare the obligation before asking any handler for an answer."""
        self.required[event.ident] = event.location()

    def record(self, event, outcome):
        """An unresolved source obligation survives visits through other dependencies."""
        self.require(event)
        prior = self.outcomes.get(event.ident)
        if prior and prior["outcome"] == EffectKind.UNKNOWN_EFFECT.value:
            return  # A second dependency inspection cannot erase an unresolved obligation.
        self.outcomes[event.ident] = dict(
            outcome=outcome.kind.value, reason=outcome.reason, **outcome.detail
        )

    def source(self, label, supported):
        """Record a separately checked origin/syntax obligation, not a rule label."""
        self.sources.append(dict(source=label, supported=bool(supported)))

    def export(self):
        """Certify only covered events and supported sources, with no unresolved gaps."""
        checks = [
            dict(
                e,
                **self.outcomes.get(i, dict(outcome="UNHANDLED", reason="missing-effect-handler")),
            )
            for i, e in self.required.items()
        ]
        complete = (
            bool(self.sources)
            and all(s["supported"] for s in self.sources)
            and not self.gaps
            and all(
                c["outcome"] in (EffectKind.NO_EFFECT.value, EffectKind.KNOWN_EFFECT.value)
                for c in checks
            )
        )
        return dict(
            rule=self.rule,
            required_events=list(self.required),
            events=self.events,
            checks=checks,
            sources=self.sources,
            gaps=self.gaps,
            complete=complete,
        )
