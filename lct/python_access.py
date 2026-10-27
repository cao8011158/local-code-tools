"""Finite access proofs for captured-source calls, not object execution or heap analysis."""

import ast
from dataclasses import dataclass
from enum import Enum


class AccessKind(str, Enum):
    """A missing path and a disproved path are different results."""

    REACHABLE = "REACHABLE"
    NOT_REACHABLE = "NOT_REACHABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Access:
    """Access alternatives with auditable source paths and unresolved gaps."""

    state: AccessKind
    evidence: tuple = ()
    gaps: tuple = ()

    def export(self):
        """Serialize only source evidence, never internal AST objects."""
        return dict(state=self.state.value, evidence=list(self.evidence), gaps=list(self.gaps))


def access(state, reason, **location):
    """Create a terminal access fact or a named unresolved source."""
    return Access(
        state, (dict(reason=reason, **location),), (reason,) if state == AccessKind.UNKNOWN else ()
    )


def combine(parts, reason):
    """All sources must be disproved; one positive source establishes reachability."""
    parts = list(parts)
    state = (
        AccessKind.REACHABLE
        if any(p.state == AccessKind.REACHABLE for p in parts)
        else AccessKind.UNKNOWN
        if any(p.state == AccessKind.UNKNOWN for p in parts)
        else AccessKind.NOT_REACHABLE
    )
    return Access(
        state,
        (dict(reason=reason),) + tuple(e for p in parts for e in p.evidence),
        tuple(dict.fromkeys(g for p in parts for g in p.gaps)),
    )


class ReceiverAccess:
    """Snapshot-local finite dependency summaries and bounded call-binding checks.

    Bindings here describe input provenance only. We do not execute statements,
    apply arbitrary function effects or construct a runtime object environment.
    """

    def __init__(self, analyzer, atom_type, result_type):
        self.a, self.Atom, self.Result = analyzer, atom_type, result_type
        self.summaries = {}
        self.references = {scope: [] for scope in analyzer.trees}
        for scope, expr, phase in analyzer.references:
            if isinstance(expr, ast.Name):
                self.references[scope].append(expr)
        self.budget = 20000
        self.call_records = {}
        self.private_bodies = {}
        self.global_names = {}
        self.captured_locals = {}
        self.lexical_children = {}
        for ident in analyzer.trees:
            parent = analyzer.nodes[ident]["parent"]
            while parent in analyzer.trees:
                self.lexical_children.setdefault(parent, []).append(ident)
                parent = analyzer.nodes[parent]["parent"]
        self.class_members = {
            i: [] for i, t in analyzer.trees.items() if isinstance(t, ast.ClassDef)
        }
        for child, node in analyzer.nodes.items():
            if node["parent"] in self.class_members and node["kind"] == "function":
                self.class_members[node["parent"]].append(child)

    def tick(self):
        """Exhaustion is a gap, never a negative access result."""
        self.budget -= 1
        if self.budget < 0:
            self.a.limited = True
        return self.budget >= 0

    def external_owner(self, scope, name):
        """Respect lexical locals, global/nonlocal declarations and skipped class namespaces."""
        if scope not in self.global_names:
            self.global_names[scope] = {
                n
                for s in ast.walk(self.a.trees[scope])
                if isinstance(s, ast.Global)
                and self.a.execution_nodes.get(id(s), (None,))[0] == scope
                for n in s.names
            }
        globals_ = self.global_names[scope]
        if name in globals_:
            return self.a.module_for[scope]
        if self.a.local_bound(scope, name):
            return scope
        current = self.a.nodes[scope].get("resolution_parent", self.a.nodes[scope]["parent"])
        while current in self.a.trees:
            t = self.a.trees[current]
            if isinstance(t, ast.ClassDef):
                current = self.a.nodes[current]["parent"]
                continue
            if (
                self.a.local_bound(current, name)
                or self.a.reaching(current, name, 10**9)
                or isinstance(t, ast.Module)
            ):
                return current
            current = self.a.nodes[current].get(
                "resolution_parent", self.a.nodes[current]["parent"]
            )
        return scope

    def value(self, scope, expr, frames, bindings):
        """Resolve input/lexical provenance at the observed invocation, not future writes."""
        if isinstance(expr, ast.Starred):
            expr = expr.value
        if isinstance(expr, ast.Name):
            key = (scope, expr.id)
            if key in bindings and not self.a.reaching(
                scope, expr.id, (expr.lineno, expr.col_offset)
            ):
                return bindings[key]
            owner = self.external_owner(scope, expr.id)
            if owner != scope:
                anchor = frames.get(owner)
                before = (anchor.lineno, anchor.col_offset) if anchor else 10**9
                if anchor is None:
                    writes = [
                        e
                        for e in self.a.effects.by_scope[owner]
                        if e.kind == "write"
                        and any(
                            isinstance(t, ast.Name) and t.id == expr.id
                            for t in self.a.write_targets(e.node)
                        )
                    ]
                    if len(writes) > 1:
                        return self.Result(reasons=frozenset(["external-binding-time-not-modeled"]))
                return self.a.resolve(owner, expr, before)
        return self.a.resolve(scope, expr)

    def reachable(
        self,
        scope,
        expr,
        receiver,
        anchor,
        *,
        mode="value",
        frames=None,
        bindings=None,
        seen=frozenset(),
    ):
        """Check explicit values, current finite slots and callable environments, in three states."""
        frames = {scope: anchor} if frames is None else frames
        bindings = {} if bindings is None else bindings
        if not self.tick():
            return access(AccessKind.UNKNOWN, "analysis-budget")
        if isinstance(expr, ast.Starred):
            expr = expr.value
            mode = "star"
        if isinstance(expr, ast.Constant):
            return access(AccessKind.NOT_REACHABLE, "literal-value", scope=scope, line=expr.lineno)
        # Ordinary synchronous functions without return values produce None. Operand
        # effects are distinct catalog events and are not suppressed by this value fact.
        call_targets = None
        if isinstance(expr, ast.Call):
            call_targets = self.value(scope, expr.func, frames, bindings)
            complete = (
                bool(call_targets.atoms)
                and not call_targets.unknown
                and self.a.requirements_complete(call_targets)
            )
            if complete and all(
                t.kind == "callable"
                and self.a.invocation_phase(t) == "ordinary-call"
                and not isinstance(self.a.trees[t.target], ast.Lambda)
                and not self.a.return_values(self.a.trees[t.target])
                for t in call_targets.atoms
            ):
                return access(AccessKind.NOT_REACHABLE, "implicit-none-return")
            if complete and all(
                t.kind == "callable"
                and (
                    isinstance(self.a.trees[t.target], ast.Lambda)
                    and isinstance(self.a.trees[t.target].body, ast.Constant)
                    or not isinstance(self.a.trees[t.target], ast.Lambda)
                    and self.a.return_values(self.a.trees[t.target])
                    and all(
                        isinstance(v, ast.Constant)
                        for v in self.a.return_values(self.a.trees[t.target])
                    )
                )
                for t in call_targets.atoms
            ):
                return access(AccessKind.NOT_REACHABLE, "literal-return-value")
        values = self.value(scope, expr, frames, bindings)
        result = self.values(values, scope, receiver, anchor, mode, frames, bindings, seen)
        if (
            call_targets is not None
            and result.state == AccessKind.NOT_REACHABLE
            and not (
                call_targets.atoms
                and not call_targets.unknown
                and all(t.kind == "class" for t in call_targets.atoms)
            )
        ):
            return access(AccessKind.UNKNOWN, "unmodeled-call-return-access")
        return result

    def values(
        self,
        values,
        scope,
        receiver,
        anchor,
        mode="value",
        frames=None,
        bindings=None,
        seen=frozenset(),
    ):
        """Inspect all origins; unknowns survive even when finite alternatives are unrelated."""
        frames = {} if frames is None else frames
        bindings = {} if bindings is None else bindings
        if not self.tick():
            return access(AccessKind.UNKNOWN, "analysis-budget")
        parts = []
        for atom in values.atoms:
            if receiver.kind == "container" and atom == receiver:
                parts.append(
                    access(AccessKind.REACHABLE, "container-reference", target=atom.target)
                )
                continue
            if atom.kind in ("instance", "deferred-result"):
                if atom.allocation and atom.allocation == receiver.allocation:
                    parts.append(
                        access(
                            AccessKind.REACHABLE,
                            "direct-argument" if atom.kind == "instance" else "deferred-receiver",
                            allocation=atom.allocation,
                        )
                    )
                elif not atom.allocation:
                    parts.append(access(AccessKind.UNKNOWN, "unresolved-allocation"))
                else:
                    origin = self.a.allocations.get(atom.allocation)
                    if atom.kind == "deferred-result":
                        parts.append(
                            access(
                                AccessKind.NOT_REACHABLE,
                                "independent-deferred-receiver",
                                allocation=atom.allocation,
                            )
                        )
                    elif origin:
                        key = ("instance", atom.allocation)
                        if key in seen:
                            parts.append(access(AccessKind.UNKNOWN, "recursive-instance-origin"))
                        else:
                            os, call = origin
                            inputs = [
                                self.reachable(
                                    os,
                                    x,
                                    receiver,
                                    call,
                                    frames=frames,
                                    bindings=bindings,
                                    seen=seen | {key},
                                )
                                for x in call.args + [k.value for k in call.keywords]
                            ]
                            inputs.append(
                                self.constructed(
                                    atom.target, os, call, receiver, frames, bindings, seen | {key}
                                )
                            )
                            inputs.append(
                                self.class_data(
                                    atom.target,
                                    scope,
                                    receiver,
                                    anchor,
                                    frames,
                                    bindings,
                                    seen | {key},
                                    instance=atom,
                                    include_methods=mode != "receiver",
                                )
                            )
                            inputs.extend(
                                self.history(
                                    scope,
                                    os,
                                    call,
                                    anchor,
                                    receiver,
                                    frames,
                                    bindings,
                                    seen | {key},
                                    "instance-association-history-not-modeled",
                                )
                            )
                            for es in {scope, os}:
                                for event in self.a.effects.before(
                                    es, anchor if es == scope else None
                                ):
                                    if event.kind != "write" or not event.reachable:
                                        continue
                                    for dest in self.a.write_targets(event.node):
                                        if not isinstance(dest, ast.Attribute):
                                            continue
                                        owners = self.value(es, dest.value, frames, bindings)
                                        if any(
                                            a.allocation == atom.allocation for a in owners.atoms
                                        ):
                                            rhs = getattr(event.node, "value", None)
                                            if rhs is not None:
                                                inputs.append(
                                                    self.reachable(
                                                        es,
                                                        rhs,
                                                        receiver,
                                                        event.node,
                                                        frames=frames,
                                                        bindings=bindings,
                                                        seen=seen | {key},
                                                    )
                                                )
                            parts.append(combine(inputs, "independent-construction-inputs"))
                    else:
                        parts.append(access(AccessKind.UNKNOWN, "unresolved-allocation-origin"))
            elif atom.kind == "class" and mode == "receiver":
                parts.append(
                    self.class_data(atom.target, scope, receiver, anchor, frames, bindings, seen)
                )
            elif atom.kind == "container":
                key = ("container", atom.target, atom.allocation)
                if key in seen:
                    parts.append(access(AccessKind.UNKNOWN, "recursive-container-origin"))
                    continue
                owner, obj = self.a.container_exprs[atom.target]
                slots, _, extra, _ = self.a.container_slots(atom, scope, anchor, None)
                contents = []
                if isinstance(obj, ast.Dict) and mode in ("value", "star"):
                    contents.extend(
                        self.reachable(
                            owner,
                            k,
                            receiver,
                            anchor,
                            frames=frames,
                            bindings=bindings,
                            seen=seen | {key},
                        )
                        for k in obj.keys
                        if k is not None
                    )
                    contents.extend(
                        self.reachable(
                            owner,
                            v,
                            receiver,
                            anchor,
                            mode="star",
                            frames=frames,
                            bindings=bindings,
                            seen=seen | {key},
                        )
                        for k, v in zip(obj.keys, obj.values)
                        if k is None
                    )
                if mode != "star" or not isinstance(obj, ast.Dict):
                    contents.extend(
                        self.values(
                            v,
                            scope,
                            receiver,
                            anchor,
                            frames=frames,
                            bindings=bindings,
                            seen=seen | {key},
                        )
                        for rs in slots.values()
                        for v in rs
                    )
                if mode == "kwargs" and (
                    not isinstance(obj, ast.Dict) or any(not isinstance(k, str) for k in slots)
                ):
                    contents.append(access(AccessKind.UNKNOWN, "unproven-keyword-unpacking"))
                if mode == "star" and isinstance(obj, ast.Dict):
                    if extra:
                        contents.append(
                            access(AccessKind.UNKNOWN, "unresolved-dictionary-key-state")
                        )
                else:
                    contents.extend(
                        self.values(
                            v,
                            scope,
                            receiver,
                            anchor,
                            frames=frames,
                            bindings=bindings,
                            seen=seen | {key},
                        )
                        for v in extra
                    )
                contents.extend(
                    self.history(
                        scope,
                        owner,
                        obj,
                        anchor,
                        atom,
                        frames,
                        bindings,
                        seen | {key},
                        "captured-container-mutation-not-modeled",
                    )
                )
                state = combine(contents, "container-element")
                parts.append(
                    Access(
                        state.state,
                        (
                            dict(
                                reason="container-source",
                                scope=owner,
                                line=obj.lineno,
                                column=obj.col_offset,
                                mode=mode,
                            ),
                        )
                        + state.evidence,
                        state.gaps,
                    )
                )
            elif atom.kind in ("callable", "context-factory", "async-context-factory"):
                if atom.bound:
                    parts.append(
                        access(
                            AccessKind.REACHABLE
                            if atom.allocation == receiver.allocation and atom.allocation
                            else AccessKind.NOT_REACHABLE
                            if atom.allocation
                            else AccessKind.UNKNOWN,
                            "bound-receiver",
                            allocation=atom.allocation,
                        )
                    )
                parts.append(self.function(atom, scope, None, receiver, frames, bindings, seen))
            elif atom.kind in ("literal", "absent-field", "possible-missing-slot"):
                parts.append(
                    access(AccessKind.NOT_REACHABLE, "finite-non-instance-value", kind=atom.kind)
                )
            else:
                parts.append(access(AccessKind.UNKNOWN, "unsupported-value-origin", kind=atom.kind))
        if values.reasons or not self.a.requirements_complete(values):
            parts.append(
                access(AccessKind.UNKNOWN, "unresolved-origin", reasons=sorted(values.reasons))
            )
        if not parts:
            invalid_rules = {
                "missing-literal-slot",
                "invalid-literal-sequence-index",
                "unbound-local-before-assignment",
                "undefined-captured-lexical-name",
                "deleted-name-binding",
            }
            parts.append(
                access(
                    AccessKind.NOT_REACHABLE
                    if values.proofs & invalid_rules
                    else AccessKind.UNKNOWN,
                    "proven-invalid-source"
                    if values.proofs & invalid_rules
                    else "unresolved-origin",
                )
            )
        return combine(parts, "value-origins")

    def history(self, scope, owner, origin, anchor, target, frames, bindings, seen, reason):
        """Prior calls need bounded dependency conclusions before old state proves independence."""
        results = []
        for es in {scope, owner}:
            for event in self.a.effects.before(es, anchor if es == scope else None):
                if event.kind != "call" or not event.reachable or event.node is origin:
                    continue
                point = self.a.effects.points.get((owner, id(origin)), 0)
                if es == owner and event.order < point:
                    continue
                history = dict(frames)
                history[es] = event.node
                targets = self.value(es, event.node.func, history, bindings)
                if targets.unknown or not targets.atoms:
                    results.append(
                        access(
                            AccessKind.UNKNOWN,
                            reason,
                            line=event.node.lineno,
                            gap="unresolved-call-history",
                        )
                    )
                for fn in targets.atoms:
                    if fn.kind == "callable":
                        if self.a.invocation_phase(fn) != "ordinary-call":
                            continue
                        dependency = self.function(
                            fn, es, event.node, target, history, bindings, seen
                        )
                    elif fn.kind == "class":
                        dependency = self.constructed(
                            fn.target, es, event.node, target, history, bindings, seen
                        )
                    else:
                        dependency = access(AccessKind.UNKNOWN, "unresolved-history-target")
                    if dependency.state != AccessKind.NOT_REACHABLE:
                        results.append(
                            Access(
                                AccessKind.UNKNOWN,
                                (dict(reason=reason, line=event.node.lineno),)
                                + dependency.evidence,
                                tuple(dict.fromkeys((reason,) + dependency.gaps)),
                            )
                        )
        return results

    def summary(self, function):
        """Cache lexical dependencies by definition/version, excluding uncalled nested bodies."""
        if function in self.summaries:
            return self.summaries[function]
        tree = self.a.trees[function]
        cutoff = (
            next(
                (
                    self.a.effects.points.get((function, id(stmt)), float("inf"))
                    for stmt in getattr(tree, "body", [])
                    if isinstance(stmt, (ast.Return, ast.Raise))
                ),
                float("inf"),
            )
            if not isinstance(tree, ast.Lambda)
            else float("inf")
        )
        refs = [
            e
            for e in self.references[function]
            if self.a.effects.points.get((function, id(e)), float("inf")) < cutoff
        ]
        calls = [
            e.node for e in self.a.effects.by_scope[function] if e.kind == "call" and e.reachable
        ]
        callees = {id(c.func) for c in calls if isinstance(c.func, ast.Name)}
        params = tree.args.posonlyargs + tree.args.args + tree.args.kwonlyargs
        params += [x for x in (tree.args.vararg, tree.args.kwarg) if x]
        captures = [
            (r, self.external_owner(function, r.id))
            for r in refs
            if id(r) not in callees and self.external_owner(function, r.id) != function
        ]
        result = dict(
            function=function,
            version_id=self.a.nodes[function]["version_id"],
            params=params,
            used_params={p.arg for p in params if any(r.id == p.arg for r in refs)},
            captures=captures,
            captures_all=[
                (r, self.external_owner(function, r.id))
                for r in refs
                if self.external_owner(function, r.id) != function
            ],
            calls=calls,
        )
        self.summaries[function] = result
        return result

    def private_body(self, function):
        """Prove a narrow body cannot publish its receiver; this is not an effect executor."""
        if function in self.private_bodies:
            return self.private_bodies[function]
        tree = self.a.trees.get(function)
        safe = isinstance(tree, ast.FunctionDef) and not tree.decorator_list
        args = tree.args.posonlyargs + tree.args.args if safe else []
        param = args[0].arg if args else None
        for stmt in tree.body if safe else []:
            if isinstance(stmt, ast.Return):
                safe = stmt.value is None or isinstance(stmt.value, ast.Constant)
                break
            if isinstance(stmt, ast.Pass):
                continue
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                safe = False
                break
            if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
                continue
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if (
                not isinstance(stmt.value, (ast.Name, ast.Constant))
                or isinstance(stmt.value, ast.Name)
                and stmt.value.id == param
                or not all(
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == param
                    for t in targets
                )
            ):
                safe = False
                break
        self.private_bodies[function] = safe
        return safe

    def captured_names(self, scope):
        """Cache potential closure cells; no complete closure-publication analysis is assumed."""
        if scope not in self.captured_locals:
            names = set()
            for child in self.lexical_children.get(scope, []):
                if isinstance(
                    self.a.trees[child], (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
                ):
                    names.update(
                        expr.id
                        for expr, owner in self.summary(child)["captures_all"]
                        if owner == scope
                    )
            self.captured_locals[scope] = names
        return self.captured_locals[scope]

    def private_input(self, scope, call, receiver, entries):
        """Prove a preexisting input cannot access a fresh, still private local allocation.

        This handles opaque input identity without pretending to know its body. All
        source/escape obligations below are required; missing history is not negative.
        """
        if not self.tick():
            return None
        if not isinstance(call.func, ast.Name) or any(
            e.state != AccessKind.NOT_REACHABLE for e in entries
        ):
            return None
        tree = self.a.trees[scope]
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        params = tree.args.posonlyargs + tree.args.args + tree.args.kwonlyargs
        if call.func.id not in {p.arg for p in params} or self.a.reaching(
            scope, call.func.id, (call.lineno, call.col_offset)
        ):
            return None
        origin = self.a.allocations.get(receiver.allocation)
        if (
            not origin
            or origin[0] != scope
            or not any(isinstance(s, ast.Assign) and s.value is origin[1] for s in tree.body)
        ):
            return None
        captured = self.captured_names(scope)
        assigned = {
            target.id
            for statement in tree.body
            if isinstance(statement, ast.Assign) and statement.value is origin[1]
            for target in statement.targets
            if isinstance(target, ast.Name)
        }
        if assigned & captured:
            return None  # A previously exported closure may observe the later store.
        member = self.a.member(receiver.target, "__init__")
        if (
            self.a.descriptor_guard(receiver.target, "", None)
            or member
            and (member.unknown or any(not self.private_body(a.target) for a in member.atoms))
        ):
            return None
        start = self.a.effects.points.get((scope, id(origin[1])))
        if start is None:
            return None
        checked = []
        for event in self.a.effects.before(scope, call):
            if event.order <= start or not event.reachable:
                continue
            if event.kind == "call":
                if event.node is origin[1]:
                    checked.append(event.ident)
                    continue
                record = self.call_records.get((scope, id(event.node), receiver.allocation))
                if not record:
                    return None
                if record.kind.value == "UNKNOWN_EFFECT":
                    return None
                if record.kind.value == "NO_EFFECT":
                    from .python_effects import valid_call_no_effect

                    if not valid_call_no_effect(dict(event.location(), **record.detail)):
                        return None
                if record.kind.value == "KNOWN_EFFECT":
                    targets = self.a.resolve(scope, event.node.func)
                    if (
                        targets.unknown
                        or not targets.atoms
                        or any(not self.private_body(a.target) for a in targets.atoms)
                    ):
                        return None
            elif event.kind == "write":
                rhs = getattr(event.node, "value", None)
                targets = self.a.write_targets(event.node)
                local = targets and all(
                    isinstance(t, ast.Name) and self.a.local_bound(scope, t.id) for t in targets
                )
                captured_store = any(isinstance(t, ast.Name) and t.id in captured for t in targets)
                if rhs is not None and (not local or captured_store):
                    value = self.reachable(scope, rhs, receiver, event.node)
                    if value.state != AccessKind.NOT_REACHABLE:
                        return None
            elif event.kind not in ("binding", "terminate"):
                return None
            checked.append(event.ident)
        return dict(
            parameter=call.func.id,
            allocation=receiver.allocation,
            creation_order=start,
            event_order=self.a.effects.points[(scope, id(call))],
            constructor_targets=sorted(a.target for a in member.atoms) if member else [],
            private_constructor=True,
            checked_events=checked,
            escape_check_complete=True,
            binding_capture_check_complete=True,
            checked_capture_names=sorted(captured),
            creation_binding_names=sorted(assigned),
        )

    def class_data(
        self,
        klass,
        scope,
        receiver,
        anchor,
        frames,
        bindings,
        seen,
        instance=None,
        include_methods=False,
    ):
        """Inspect finite class storage and inherited declarations, not an object heap."""
        key = ("class-data", klass, instance.allocation if instance else "")
        if not self.tick() or key in seen:
            return access(AccessKind.UNKNOWN, "recursive-or-budget-class-dependency")
        parts = []
        if include_methods:
            for definition in self.class_members.get(klass, []):
                parts.append(
                    self.function(
                        self.Atom(
                            "callable", definition, True, instance.target, instance.allocation
                        ),
                        scope,
                        None,
                        receiver,
                        frames,
                        bindings,
                        seen | {key},
                    )
                )
        for statement in self.a.statements[klass]:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None:
                parts.append(
                    self.reachable(
                        klass,
                        statement.value,
                        receiver,
                        statement,
                        frames=frames,
                        bindings=bindings,
                        seen=seen | {key},
                    )
                )
        for event in self.a.effects.before(scope, anchor):
            if event.kind != "write" or not event.reachable:
                continue
            for dest in self.a.write_targets(event.node):
                if isinstance(dest, ast.Attribute):
                    owners = self.value(scope, dest.value, frames, bindings)
                    if any(a.kind == "class" and a.target == klass for a in owners.atoms):
                        rhs = getattr(event.node, "value", None)
                        if rhs is not None:
                            parts.append(
                                self.reachable(
                                    scope,
                                    rhs,
                                    receiver,
                                    event.node,
                                    frames=frames,
                                    bindings=bindings,
                                    seen=seen | {key},
                                )
                            )
        parent = self.a.nodes[klass]["parent"]
        for base in self.a.trees[klass].bases:
            origins = self.value(parent, base, frames, bindings)
            if origins.unknown or not origins.atoms:
                parts.append(access(AccessKind.UNKNOWN, "unresolved-base-dependency"))
            for origin in origins.atoms:
                if origin.kind == "class":
                    parts.append(
                        self.class_data(
                            origin.target,
                            scope,
                            receiver,
                            anchor,
                            frames,
                            bindings,
                            seen | {key},
                            instance,
                            include_methods,
                        )
                    )
                else:
                    parts.append(access(AccessKind.UNKNOWN, "unsupported-base-dependency"))
        return combine(parts, "class-storage-dependencies")

    def constructed(self, klass, scope, call, receiver, frames, bindings, seen=frozenset()):
        """Inspect a verified initializer's inputs/dependencies, without constructing it."""
        if self.a.descriptor_guard(klass, "", None):
            return access(AccessKind.UNKNOWN, "unsupported-construction-protocol")
        initial = self.a.member(klass, "__init__")
        if initial is None:
            return access(AccessKind.NOT_REACHABLE, "object-default-construction", target=klass)
        if initial.unknown:
            return access(AccessKind.UNKNOWN, "unresolved-initializer")
        allocation = f"{scope}:{call.lineno}:{call.col_offset}"
        self.a.allocations.setdefault(allocation, (scope, call))
        return combine(
            (
                self.function(
                    self.Atom(a.kind, a.target, True, klass, allocation),
                    scope,
                    call,
                    receiver,
                    frames,
                    bindings,
                    seen,
                )
                for a in initial.atoms
            ),
            "constructor-dependencies",
        )

    def function(
        self,
        atom,
        scope,
        call,
        receiver,
        frames,
        bindings,
        seen=frozenset(),
        environment_only=False,
    ):
        """Inspect a finite function dependency summary, including bounded transitive calls."""
        function = atom.target
        key = ("function", function, atom.allocation)
        if not self.tick() or key in seen:
            return access(
                AccessKind.UNKNOWN,
                "analysis-budget" if self.budget < 0 else "recursive-call-dependency",
            )
        tree = self.a.trees.get(function)
        if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return access(AccessKind.UNKNOWN, "unresolved-call-target")
        if not isinstance(tree, ast.Lambda) and tree.decorator_list:
            if {ast.unparse(d) for d in tree.decorator_list} - {"classmethod", "staticmethod"}:
                return access(AccessKind.UNKNOWN, "decorated-call-dependency")
        origin = self.a.allocations.get(receiver.allocation)
        if origin and origin[0] == function and not environment_only:
            body = (
                [
                    s
                    for s in tree.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                ]
                if not isinstance(tree, ast.Lambda)
                else []
            )
            if not (
                len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is origin[1]
            ):
                return access(AccessKind.UNKNOWN, "local-allocation-effects-not-modeled")
        summary = self.summary(function)
        local = dict(bindings)
        parts = []
        params = tree.args.posonlyargs + tree.args.args
        positional = params[1:] if atom.bound else params
        if atom.bound and params:
            value = self.Result(
                frozenset(
                    [
                        self.Atom(
                            "class"
                            if any(
                                ast.unparse(d) == "classmethod"
                                for d in getattr(tree, "decorator_list", [])
                            )
                            else "instance",
                            atom.receiver,
                            allocation=atom.allocation,
                        )
                    ]
                ),
                proofs=frozenset(["bound-receiver-origin"]),
            )
            local[(function, params[0].arg)] = value
        for i, p in enumerate(positional + tree.args.kwonlyargs):
            supplied = None
            if call:
                if (
                    i < len(positional)
                    and i < len(call.args)
                    and not isinstance(call.args[i], ast.Starred)
                ):
                    supplied = call.args[i]
                supplied = next((k.value for k in call.keywords if k.arg == p.arg), supplied)
            if supplied is not None:
                local[(function, p.arg)] = self.value(scope, supplied, frames, bindings)
            else:
                default = self.a.parameter_default(tree, p.arg)
                if default is not None:
                    parent = self.a.nodes[function].get(
                        "resolution_parent", self.a.nodes[function]["parent"]
                    )
                    value = self.value(parent, default, frames, bindings)
                    local[(function, p.arg)] = value
                    if p.arg in summary["used_params"]:
                        parts.append(
                            self.values(
                                value,
                                parent,
                                receiver,
                                call or default,
                                frames=frames,
                                bindings=bindings,
                                seen=seen | {key},
                            )
                        )
        for expr, owner in summary["captures"]:
            value = self.value(function, expr, frames, local)
            result = self.values(
                value,
                owner,
                receiver,
                frames.get(owner, call or expr),
                frames=frames,
                bindings=local,
                seen=seen | {key},
            )
            label = (
                "closure-binding"
                if not isinstance(self.a.trees[owner], ast.Module)
                else "external-binding"
            )
            parts.append(
                Access(
                    result.state,
                    (dict(reason=label, name=expr.id, scope=owner, line=expr.lineno),)
                    + result.evidence,
                    result.gaps,
                )
            )
        if not environment_only:
            childframes = dict(frames)
            for child in summary["calls"]:
                childframes[function] = child
                targets = self.value(function, child.func, childframes, local)
                if (
                    targets.unknown
                    or not targets.atoms
                    or not self.a.requirements_complete(targets)
                ):
                    parts.append(
                        access(
                            AccessKind.UNKNOWN,
                            "unresolved-transitive-call-target",
                            line=child.lineno,
                        )
                    )
                    continue
                args = [
                    self.reachable(
                        function,
                        x,
                        receiver,
                        child,
                        frames=childframes,
                        bindings=local,
                        seen=seen | {key},
                    )
                    for x in child.args
                ]
                args += [
                    self.reachable(
                        function,
                        k.value,
                        receiver,
                        child,
                        mode="kwargs" if k.arg is None else "value",
                        frames=childframes,
                        bindings=local,
                        seen=seen | {key},
                    )
                    for k in child.keywords
                ]
                parts.extend(args)
                for target in targets.atoms:
                    if (
                        target.kind == "callable"
                        and self.a.invocation_phase(target) != "ordinary-call"
                    ):
                        continue
                    if target.kind == "callable":
                        parts.append(
                            self.function(
                                target, function, child, receiver, childframes, local, seen | {key}
                            )
                        )
                    elif target.kind == "class":
                        parts.append(
                            self.constructed(
                                target.target,
                                function,
                                child,
                                receiver,
                                childframes,
                                local,
                                seen | {key},
                            )
                        )
                    else:
                        parts.append(
                            access(AccessKind.UNKNOWN, "unsupported-transitive-call-target")
                        )
        state = combine(parts, "finite-function-dependencies")
        return Access(
            state.state,
            (
                dict(
                    reason="definition-dependencies",
                    function=function,
                    version_id=summary["version_id"],
                    invocation_scope=scope,
                    call_line=call.lineno if call else None,
                ),
            )
            + state.evidence,
            state.gaps,
        )
