"""Snapshot-local execution events and independent effect coverage receipts.

This inventory observes syntax, never executes it. Conditional/unordered regions are
kept even when no effect handler supports them; deferred bodies have their own scope.
"""

import ast
import hashlib
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
        location = dict(
            event_id=self.ident,
            kind=self.kind,
            event_kind=self.kind,
            syntax=type(self.node).__name__,
            scope=self.scope,
            line=self.node.lineno,
            column=self.node.col_offset,
            conditional=self.conditional,
            ordered=self.ordered,
            reachable=self.reachable,
            phase=self.phase,
        )
        if isinstance(self.node, ast.ClassDef):
            location["syntax_digest"] = class_syntax_digest(self.node)
        return location


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
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.visit(
                    item.context_expr,
                    scope,
                    conditional,
                    ordered,
                    reachable,
                )
                # Enter protocol runs before the as-target and suite.
                self.add(
                    scope, node, "region",
                    conditional, False, reachable, phase,
                )
                self.visit(
                    item.optional_vars,
                    scope,
                    True,
                    False,
                    reachable,
                )
            self.block(node.body, scope, True, False, reachable)
            # Exit protocol may affect reads following the statement.
            self.add(
                scope, node, "region",
                conditional, False, reachable, phase,
            )
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


def class_syntax_digest(node):
    """Bind the local class proof to captured syntax, ignoring only source offsets."""
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def inert_class_definition(node):
    """Recognize only baseless, undecorated classes with inert declaration headers.

    Method bodies are deliberately not inspected: defining them does not run them.
    No metaclass, descriptor, annotation-name or default-call effects are inferred.
    """
    if (
        not isinstance(node, ast.ClassDef)
        or node.bases
        or node.keywords
        or node.decorator_list
        or getattr(node, "type_params", [])
    ):
        return False

    for statement in node.body:
        if (
            isinstance(statement, ast.Pass)
            or isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
        ):
            continue
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if statement.decorator_list or getattr(statement, "type_params", []):
            return False
        headers = [statement.args] + ([statement.returns] if statement.returns is not None else [])
        if any(
            not isinstance(part, (ast.arguments, ast.arg, ast.Constant))
            for header in headers
            for part in ast.walk(header)
        ):
            return False
    return True


def implicit_execution_effect(event):
    """Unsupported implicit execution is unknown, never disproved by missing references."""
    if event.kind == "scope-execution" and inert_class_definition(event.node):
        proof = dict(
            rule="inert-class-definition",
            event_id=event.ident,
            source=ast.unparse(event.node),
            line=event.node.lineno,
            column=event.node.col_offset,
        )
        return EffectOutcome(
            EffectKind.NO_EFFECT, "inert-class-definition", detail=dict(execution_evidence=proof)
        )
    reason = (
        "implicit-decorator-effects-not-modeled"
        if event.kind == "implicit-call"
        else "unsupported-protocol-region"
        if event.kind == "region"
        else "unsupported-class-definition-effects"
    )
    return EffectOutcome(EffectKind.UNKNOWN_EFFECT, reason)


def valid_implicit_no_effect(check):
    """Only an unreachable event or the exact local inert-class rule has a No-effect proof."""
    if not check.get("reachable", True):
        return True
    if (
        check.get("event_kind", check.get("kind")) != "scope-execution"
        or check.get("syntax") != "ClassDef"
    ):
        return False
    proof = check.get("execution_evidence", {})
    if not isinstance(proof, dict):
        return False
    if (
        proof.get("rule") != "inert-class-definition"
        or proof.get("event_id") != check.get("event_id")
        or proof.get("line") != check.get("line")
        or proof.get("column") != check.get("column")
        or not isinstance(proof.get("source"), str)
    ):
        return False
    try:
        parsed = ast.parse(proof["source"]).body
    except (SyntaxError, ValueError, TypeError):
        return False
    return (
        len(parsed) == 1
        and inert_class_definition(parsed[0])
        and class_syntax_digest(parsed[0]) == check.get("syntax_digest")
    )


def valid_call_no_effect(check):
    """A field-call NO_EFFECT needs checked access, phase, summary or creation evidence."""
    if not check.get("reachable", True):
        return True
    proof = check.get("call_access")
    if not isinstance(proof, dict):
        return False
    basis = check.get("no_effect_basis")
    state = proof.get("target_state")
    entries = proof.get("entries")
    if not isinstance(entries, list):
        return False
    if basis == "creation-order":
        return (
            state == "BEFORE_ALLOCATION"
            and bool(proof.get("allocation"))
            and isinstance(proof.get("event_order"), int)
            and isinstance(proof.get("creation_order"), int)
            and proof["event_order"] < proof["creation_order"]
        )
    if basis == "private-input":
        private = proof.get("private_input", {})
        return (
            state == "PREEXISTING_INPUT"
            and bool(private.get("parameter"))
            and bool(private.get("allocation"))
            and private.get("private_constructor") is True
            and private.get("escape_check_complete") is True
            and private.get("binding_capture_check_complete") is True
            and isinstance(private.get("checked_capture_names"), list)
            and bool(private.get("creation_binding_names"))
            and not set(private["checked_capture_names"]) & set(private["creation_binding_names"])
            and isinstance(private.get("checked_events"), list)
            and private.get("event_order", -1) > private.get("creation_order", 0)
            and all(
                e.get("state") == "NOT_REACHABLE" and not e.get("gaps") and bool(e.get("evidence"))
                for e in entries
            )
        )
    definitions = proof.get("definitions", [])
    if (
        state != "RESOLVED"
        or not proof.get("targets")
        or {d.get("target") for d in definitions} != set(proof["targets"])
        or not all(d.get("version_id") for d in definitions)
    ):
        return False
    if basis == "construction":
        return bool(proof.get("allocation"))
    if basis == "deferred-creation":
        return bool(proof.get("phases")) and all(
            p
            in (
                "coroutine-create",
                "generator-create",
                "async-generator-create",
                "context-manager-create",
            )
            for p in proof["phases"]
        )
    if basis == "unused-input-summary":
        unused = proof.get("unused_inputs", {})
        return (
            unused.get("used_parameters") == []
            and isinstance(unused.get("dependencies"), list)
            and all(
                e.get("state") == "NOT_REACHABLE" and not e.get("gaps") and e.get("evidence")
                for e in unused["dependencies"]
            )
            and valid_coverage(check.get("summary_coverage"))
        )
    if not all(
        e.get("state") == "NOT_REACHABLE" and not e.get("gaps") and bool(e.get("evidence"))
        for e in entries
    ):
        return False
    if basis == "method-summary":
        return valid_coverage(check.get("summary_coverage"))
    return basis == "all-inputs-disproved" and bool(entries)


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
        and all(
            c.get("outcome") == EffectKind.NO_EFFECT.value and valid_implicit_no_effect(c)
            for c in checks
            if c.get("event_kind", c.get("kind")) in ("implicit-call", "region", "scope-execution")
        )
        and all(
            valid_call_no_effect(c)
            for c in checks
            if receipt.get("rule") in ("instance-field-coverage", "finite-method-summary")
            and c.get("event_kind", c.get("kind")) == "call"
            and c.get("outcome") == EffectKind.NO_EFFECT.value
        )
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
        checks = []
        for ident, location in self.required.items():
            check = dict(
                location,
                **self.outcomes.get(
                    ident, dict(outcome="UNHANDLED", reason="missing-effect-handler")
                ),
            )
            # Handler details may describe a method; they cannot rewrite event reachability/type.
            check.update({k: v for k, v in location.items() if k != "kind"})
            checks.append(check)
        complete = (
            bool(self.sources)
            and all(s["supported"] for s in self.sources)
            and not self.gaps
            and all(
                c["outcome"] in (EffectKind.NO_EFFECT.value, EffectKind.KNOWN_EFFECT.value)
                for c in checks
            )
        )
        receipt = dict(
            rule=self.rule,
            required_events=list(self.required),
            events=self.events,
            checks=checks,
            sources=self.sources,
            gaps=self.gaps,
            complete=complete,
        )
        receipt["complete"] = valid_coverage(receipt)
        return receipt
