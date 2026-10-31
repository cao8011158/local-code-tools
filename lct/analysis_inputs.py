"""Bounded captured query input scopes, not a complete semantic read proof."""

from .common import canonical, digest

LIMIT = 20000
CAPTURE = "capture:all-captured-python"


class AnalysisInputs:
    def __init__(self, modules, *, limit=LIMIT):
        self.modules = modules
        self.limit = limit
        self.scopes = {}
        self.members = {}
        self.member_count = 0
        self.consumers = set()
        self.component_ids = {}
        self.truncated = False

    def observe(self, consumer_module, component):
        if consumer_module not in self.modules:
            self.truncated = True
            return
        if component is None:
            ident, kind, members = CAPTURE, "capture", ()
        else:
            ident = self.component_ids.get(component)
            if ident is not None and (ident, consumer_module) in self.consumers:
                return
            if consumer_module not in component:
                self.truncated = True
                return
            if ident is None:
                if any(m not in self.modules for m in component):
                    self.truncated = True
                    return
                ident = "component:" + digest(canonical(sorted(component)))
                self.component_ids[component] = ident
            kind, members = "component", component
        if (ident, consumer_module) in self.consumers:
            return
        extra = 1 + len(members) if ident not in self.scopes else 0
        if len(self.scopes) + self.member_count + len(self.consumers) + extra + 1 > self.limit:
            self.truncated = True
            return
        if ident not in self.scopes:
            self.scopes[ident] = kind
            self.members[ident] = frozenset(members)
            self.member_count += len(members)
        self.consumers.add((ident, consumer_module))

    def export(self):
        def row(scope, module):
            owner = self.modules[module]
            return dict(scope_id=scope, module_id=module, repository=owner["repository"],
                        path=owner["path"])
        return dict(scopes=[dict(id=ident, kind=kind) for ident, kind in sorted(self.scopes.items())],
                    members=[row(ident, module) for ident, members in sorted(self.members.items())
                             for module in sorted(members)],
                    consumers=[row(ident, module) for ident, module in sorted(self.consumers)],
                    truncated=self.truncated)


def merge(old, new, *, selected, old_nodes, new_nodes, verified):
    """Replace selected consumers; reject retained scope touching selected input."""
    if old is None or new is None or old["truncated"] or new["truncated"]:
        return None
    def owner(module):
        n = old_nodes.get(module)
        return (n["repository"], n["path"]) if n else None
    scopes = {r["id"]: r["kind"] for r in new["scopes"]}
    members = {(r["scope_id"], r["module_id"]): r for r in new["members"]}
    consumers = {(r["scope_id"], r["module_id"]): r for r in new["consumers"]}
    old_members = {}
    old_scopes = {r["id"]: r["kind"] for r in old["scopes"]}
    for record in old["members"]:
        old_members.setdefault(record["scope_id"], []).append(record)
    retained_by_scope = {}
    for record in old["consumers"]:
        consumer = record["module_id"]
        if owner(consumer) not in selected:
            if owner(consumer) not in verified or consumer not in new_nodes:
                return None
            retained_by_scope.setdefault(record["scope_id"], []).append(record)
    for ident, retained in retained_by_scope.items():
        kind = old_scopes.get(ident)
        if kind == "capture" and selected:
            return None
        if kind == "component" and any(owner(m["module_id"]) in selected or
                owner(m["module_id"]) not in verified or m["module_id"] not in new_nodes
                for m in old_members.get(ident, ())):
            return None
        if kind not in {"capture", "component"} or scopes.get(ident, kind) != kind:
            return None
        scopes[ident] = kind
        for member in old_members.get(ident, ()):
            key = ident, member["module_id"]
            if key in members and members[key] != member:
                return None
            members[key] = member
        for record in retained:
            consumers[ident, record["module_id"]] = record
    if len(scopes) + len(members) + len(consumers) > LIMIT:
        return None
    return dict(scopes=[dict(id=i, kind=k) for i, k in sorted(scopes.items())],
                members=[members[k] for k in sorted(members)],
                consumers=[consumers[k] for k in sorted(consumers)], truncated=False)


def read(db):
    return dict(scopes=[dict(id=i, kind=k) for i, k in db.execute(
                    "select id,kind from analysis_input_scopes order by id")],
                members=[dict(scope_id=s, module_id=m, repository=r, path=p)
                         for s, m, r, p in db.execute(
                             "select scope_id,module_id,repository,path from analysis_input_members order by scope_id,module_id")],
                consumers=[dict(scope_id=s, module_id=m, repository=r, path=p)
                           for s, m, r, p in db.execute(
                               "select scope_id,module_id,repository,path from analysis_input_consumers order by scope_id,module_id")])


def valid(payload, modules):
    scopes = {r["id"]: r["kind"] for r in payload["scopes"]}
    if (len(scopes) != len(payload["scopes"]) or
            any(k not in {"capture", "component"} or
                (i == CAPTURE) != (k == "capture") or
                (k == "component" and not i.startswith("component:"))
                for i, k in scopes.items())):
        return False
    members = {}
    member_ids_by_scope = {}
    for r in payload["members"]:
        s, m = r["scope_id"], r["module_id"]
        if (s not in scopes or scopes[s] != "component" or
                modules.get(m) != (r["repository"], r["path"]) or
                (s, m) in members):
            return False
        members[s, m] = r
        member_ids_by_scope.setdefault(s, []).append(m)
    consumers = set()
    consumer_count_by_scope = {}
    for r in payload["consumers"]:
        s, m = r["scope_id"], r["module_id"]
        if (s not in scopes or modules.get(m) != (r["repository"], r["path"]) or
                (s, m) in consumers or
                scopes[s] == "component" and (s, m) not in members):
            return False
        consumers.add((s, m))
        consumer_count_by_scope[s] = consumer_count_by_scope.get(s, 0) + 1
    if len(scopes) + len(members) + len(consumers) > LIMIT:
        return False
    for ident, kind in scopes.items():
        if not consumer_count_by_scope.get(ident):
            return False
        if kind == "component":
            ids = member_ids_by_scope.get(ident)
            if not ids:
                return False
            expected = "component:" + digest(canonical(sorted(ids)))
            if ident != expected:
                return False
    return True
