"""Fifth bounded experiment: validate and rebind typed retained evidence."""
import ast
import importlib.util
import json
from collections import defaultdict, deque
from pathlib import Path
from lct.evidence_reuse import EvidenceReuseRejected, RebindContext

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("directional_v1", HERE / "run.py")
v1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v1)
Analyzer = v1.graph_module.Analyzer


def catalog(sources):
    nodes, trees = v1.local.capture(sources)
    graph = v1.graph_module.Graph(nodes, trees, [v1.local.REPO])
    analyzer = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    return graph, analyzer


def direct_return_values(graph, analyzer, path, name):
    found = [(ident, tree) for ident, tree in analyzer.trees.items()
             if graph.nodes[ident]["path"] == path and graph.nodes[ident]["qualname"] == name
             and isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(found) != 1:
        return None
    ident, fn = found[0]
    results = []
    for statement in ast.walk(fn):
        if not isinstance(statement, ast.Return):
            continue
        if statement.value is None:
            results.append(("bare",))
            continue
        resolved = analyzer.resolve(ident, statement.value)
        results.append((tuple(sorted((a.kind, a.target) for a in resolved.atoms)),
                        tuple(sorted(resolved.reasons)), tuple(sorted(resolved.proofs)),
                        analyzer.requirements_complete(resolved)))
    return tuple(results)


def call_shapes(source):
    if source is None:
        return ()
    return tuple(ast.dump(x, include_attributes=False) for x in ast.walk(ast.parse(source))
                 if isinstance(x, ast.Call))


last_summary_cost = None


def state_may_escape(value):
    """Equal atoms prove no field/state equivalence for returned non-literals.

    This intentionally has a small safe stopping set. A literal with a complete
    resolution cannot carry changed constructor fields; anything else (including
    an unresolved/empty result) is conservatively propagated to return users.
    """
    if value is None:
        return True
    for row in value:
        if row == ("bare",):
            continue
        atoms, reasons, _proofs, complete = row
        if reasons or not complete or not atoms or any(kind != "literal" for kind, _ in atoms):
            return True
    return False


def function_body_changed(old_fn, new_fn):
    return ast.dump(old_fn, include_attributes=False) != ast.dump(new_fn, include_attributes=False)


def definition_index(graph, analyzer):
    """Full (path, qualname, kind) identities; ambiguous definitions are not guessed."""
    found = defaultdict(list)
    for ident, tree in analyzer.trees.items():
        node = graph.nodes[ident]
        if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node["path"], node["qualname"], node["kind"]].append((ident, tree))
    return found


def unique(index, key):
    values = index.get(key, ())
    return values[0] if len(values) == 1 else None


def schedule(before, after, old):
    global last_summary_cost
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    ids = {n["node_id"]: n for n in old["nodes"]}
    old_g, old_a = catalog(before)
    new_g, new_a = catalog(after)
    old_defs, new_defs = definition_index(old_g, old_a), definition_index(new_g, new_a)
    callers, callees = defaultdict(set), defaultdict(set)
    contains_parent = {}
    for e in old["edges"]:
        if e["kind"] == "CALLS" and e["source"] in ids and e["target"] in ids:
            callers[e["target"]].add(e["source"])
            callees[e["source"]].add(e["target"])
        if e["kind"] == "CONTAINS" and e["target"] in ids:
            contains_parent[e["target"]] = e["source"]
    selected, events, return_queue = set(changed), [], deque()
    summary_cache = {}
    def summary(side, path, name):
        key = side, path, name
        if key not in summary_cache:
            graph, analyzer = (old_g, old_a) if side == "old" else (new_g, new_a)
            summary_cache[key] = direct_return_values(graph, analyzer, path, name)
        return summary_cache[key]
    try:
        for path in sorted(changed):
            old_top = {key[1] for key in old_defs if key[0] == path and key[2] == "function"
                       and "." not in key[1]}
            new_top = {key[1] for key in new_defs if key[0] == path and key[2] == "function"
                       and "." not in key[1]}
            if path not in before or path not in after or old_top != new_top:
                selected.update(v1.static_importers(before, v1.module_name(path)))
                selected.update(v1.static_importers(after, v1.module_name(path)))
                events.append((path, "module-boundary/importers"))
            for name in sorted(old_top & new_top):
                key = path, name, "function"
                prior_def, current_def = unique(old_defs, key), unique(new_defs, key)
                if prior_def is None or current_def is None:
                    continue
                ident, old_fn = prior_def
                _, new_fn = current_def
                old_value = summary("old", path, name)
                new_value = summary("new", path, name)
                # Literal/container payloads can be semantically relevant even
                # when both resolutions have no callable atoms.
                if (old_value != new_value or v1.returns(old_fn) != v1.returns(new_fn)
                    or (function_body_changed(old_fn, new_fn)
                        and (state_may_escape(old_value) or state_may_escape(new_value)))):
                    return_queue.append(ident)
                    events.append((path, name + ":return-impact"))
            # A constructor's implicit None return says nothing about the state
            # of the constructed instance. Follow the actual containing class,
            # then its old CALLS consumers. Full qualnames isolate same-name methods.
            init_keys = {key for key in old_defs.keys() | new_defs.keys()
                         if key[0] == path and key[2] == "function"
                         and key[1].endswith(".__init__")}
            for key in sorted(init_keys):
                prior_def, current_def = unique(old_defs, key), unique(new_defs, key)
                if prior_def and current_def and not function_body_changed(prior_def[1], current_def[1]):
                    continue
                parent = contains_parent.get(prior_def[0]) if prior_def else None
                if parent is None and current_def:
                    # Added __init__ on an existing class: match its exact class
                    # identity across captures and use the old graph's CALLS.
                    class_key = path, key[1].rsplit(".", 1)[0], "class"
                    old_class = unique(old_defs, class_key)
                    new_class = unique(new_defs, class_key)
                    if old_class and new_class:
                        parent = old_class[0]
                if parent in ids and ids[parent]["kind"] == "class":
                    return_queue.append(parent)
                    events.append((path, key[1] + ":constructor-state-impact"))
            if call_shapes(before.get(path)) != call_shapes(after.get(path)):
                targets = {target for source, row in ids.items() if row["path"] == path
                           for target in callees[source]}
                for item in new_a.sites:
                    owner = item["execution_owner"]
                    if new_g.nodes[owner]["path"] != path or item.get("_call") is None:
                        continue
                    for atom in new_a.resolve(owner, item["_expr"]).atoms:
                        if atom.target in new_g.nodes:
                            targets.add(atom.target)
                for target in targets:
                    node = (ids.get(target) or new_g.nodes.get(target))
                    if node and node["kind"] == "function":
                        key = node["path"], node["qualname"], node["kind"]
                        definition = unique(old_defs, key) or unique(new_defs, key)
                        fn = definition[1] if definition else None
                        if v1.invokes_parameter(fn):
                            selected.add(node["path"])
                events.append((path, "call-shape/callee-parameter"))
        visited = set()
        while return_queue:
            target = return_queue.popleft()
            if target in visited:
                continue
            visited.add(target)
            for caller in callers[target]:
                selected.add(ids[caller]["path"])
                path = ids[caller]["path"]
                name = ids[caller]["qualname"]
                # Follow actual changed return summaries, including forwarding
                # through a local binding; finite graph worklist, each ID once.
                prior, current = summary("old", path, name), summary("new", path, name)
                if prior != current or state_may_escape(prior) or state_may_escape(current):
                    return_queue.append(caller)
        last_summary_cost = dict(old_ast_context_files=len(before), new_ast_context_files=len(after),
                                 old_jedi_queries=old_a.executed_queries,
                                 new_jedi_queries=new_a.executed_queries,
                                 old_associations=20000-old_a.budget,
                                 new_associations=20000-new_a.budget,
                                 summary_evaluations=len(summary_cache))
        return selected & set(after), events
    finally:
        old_a.close()
        new_a.close()


def run_case(*case):
    result = v1.run_case(*case)
    result["directional"]["summary_cost"] = last_summary_cost
    return result


def independent_cases():
    spec = importlib.util.spec_from_file_location("independent_cases", HERE / "independent_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def transitive_local_case():
    before = {"src/a.py": "class One:\n def alpha(self): pass\nclass Two:\n def beta(self): pass\ndef make(): return One()\n",
              "src/b.py": "from a import make\ndef forward():\n result = make()\n return result\n",
              "src/c.py": "from b import forward\ndef consume(): forward().alpha()\n"}
    yield "transitive_return_through_local", before, {**before,
          "src/a.py": before["src/a.py"].replace("return One()", "return Two()")}


def object_state_cases():
    factory = ("def first(): pass\ndef second(): pass\n"
               "class Box:\n def __init__(self, cb): self.cb=cb\n"
               "def factory(): return Box(first)\n")
    direct = {"src/a.py": factory,
              "src/b.py": "from a import factory\ndef run(): factory().cb()\n"}
    yield "direct_same_class_different_field", direct, {
        **direct, "src/a.py": factory.replace("Box(first)", "Box(second)")}
    forwarded = {**direct,
                 "src/b.py": "from a import factory\ndef forward():\n item=factory()\n return item\n",
                 "src/c.py": "from b import forward\ndef run(): forward().cb()\n"}
    yield "forwarded_same_class_different_field", forwarded, {
        **forwarded, "src/a.py": factory.replace("Box(first)", "Box(second)")}
    scalar = {"src/a.py": "def factory():\n unused=1\n return 7\n",
              "src/b.py": "from a import factory\ndef run(): factory()\n"}
    yield "unrelated_local_scalar_control", scalar, {
        **scalar, "src/a.py": scalar["src/a.py"].replace("unused=1", "unused=2")}


def independent_v2_cases():
    spec = importlib.util.spec_from_file_location("independent_v2_cases", HERE / "independent_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def independent_v3_cases():
    spec = importlib.util.spec_from_file_location("independent_v3_cases", HERE / "independent_v3.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def constructor_cases():
    source = ("def first(): pass\ndef second(): pass\n"
              "class Alpha:\n def __init__(self): self.cb=first\n"
              "class Beta:\n def __init__(self): self.cb=first\n"
              "def make_alpha(): return Alpha()\n"
              "def make_beta(): return Beta()\n")
    before = {"src/a.py": source,
              "src/b.py": "from a import make_alpha\ndef run(): make_alpha().cb()\n",
              "src/c.py": "from a import make_beta\ndef run(): make_beta().cb()\n"}
    yield "same_named_initializers_isolated", before, {
        **before, "src/a.py": source.replace("class Alpha:\n def __init__(self): self.cb=first",
                                          "class Alpha:\n def __init__(self): self.cb=second")}
    source = ("def first(): pass\ndef second(): pass\n"
              "class Box:\n def __init__(self): self.cb=first\n"
              "def factory():\n Box()\n return 7\n")
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\ndef run(): factory()\n"}
    yield "constructor_change_constant_factory_control", before, {
        **before, "src/a.py": source.replace("self.cb=first", "self.cb=second")}
    before = {"src/a.py": "def first(): pass\ndef second(): pass\nclass Alpha:\n def __init__(self): self.cb=first\ndef make(): return Alpha()\n",
              "src/d.py": "def first(): pass\nclass Beta:\n def __init__(self): self.cb=first\ndef make(): return Beta()\n",
              "src/b.py": "from a import make\ndef run(): make().cb()\n",
              "src/c.py": "from d import make\ndef run(): make().cb()\n"}
    yield "same_named_initializers_separate_files", before, {
        **before, "src/a.py": before["src/a.py"].replace("self.cb=first", "self.cb=second")}
    before = {"src/a.py": "def first(): pass\nclass Box: pass\ndef factory(): return Box()\n",
              "src/b.py": "from a import factory\ndef run(): factory().cb()\n"}
    yield "added_initializer_existing_class", before, {
        **before, "src/a.py": before["src/a.py"].replace("class Box: pass",
            "class Box:\n def __init__(self): self.cb=first")}


def candidate(before, after, old):
    selected, events = schedule(before, after, old)
    old_nodes = {n["node_id"]: n for n in old["nodes"]}
    fresh_nodes, new_trees = v1.local.capture(after)
    new_nodes = {n["node_id"]: n for n in fresh_nodes}
    _, old_trees = v1.local.capture(before)
    rejected = set()
    context = RebindContext(old_nodes=old_nodes, new_nodes=new_nodes,
                            old_trees=old_trees, new_trees=new_trees,
                            selected_paths=selected)

    # Preparatory catalog is global, but no fresh full oracle participates in
    # validation or selection. Rejected owners enter the real selective build.
    while True:
        keep_edges, keep_sites, new_rejections = [], [], set()
        for edge in old["edges"]:
            if edge["kind"] != "CALLS":
                continue
            owner = edge["source"]
            path = old_nodes.get(owner, {}).get("path")
            if path not in after or path in selected:
                continue
            try:
                keep_edges.append(context.rebind(edge, owner_id=owner))
            except EvidenceReuseRejected:
                new_rejections.add(path)
        for site in old["info"]["sites"]:
            owner = site["execution_owner"]
            path = old_nodes.get(owner, {}).get("path")
            if path not in after or path in selected:
                continue
            try:
                keep_sites.append(context.rebind(site, owner_id=owner))
            except EvidenceReuseRejected:
                new_rejections.add(path)
        new_rejections -= selected
        if not new_rejections:
            break
        selected.update(new_rejections)
        rejected.update(new_rejections)

    partial = v1.selective_build(after, selected)
    new_ids = {n["node_id"]: n["path"] for n in partial["nodes"]}
    edges = [e for e in partial["edges"] if e["kind"] != "CALLS" or
             new_ids.get(e["source"]) in selected] + keep_edges
    sites = partial["info"]["sites"] + keep_sites
    return dict(nodes=partial["nodes"], edges=edges, info=dict(sites=sites)), dict(
        selected=sorted(selected), events=events,
        rejected_owner_paths=sorted(rejected),
        definition_match_evaluations=context.match_evaluations,
        preparatory_old_ast_files=len(before), preparatory_new_ast_files=len(after),
        analyzed_outer_sites=partial["info"]["call_sites"],
        actual_jedi_queries=partial["info"]["jedi_queries_executed"],
        association_evaluations=partial["info"]["association_evaluations"],
        full_ast_context_files=len(after), non_call_relation_pass="all files")


def independent_v4_cases():
    spec = importlib.util.spec_from_file_location("independent_v4_cases", HERE / "independent_v4.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


if __name__ == "__main__":
    v1.schedule = schedule
    v1.candidate = candidate
    results = [run_case(*case) for case in (*v1.cases(), *independent_cases(),
                                           *transitive_local_case(), *independent_v2_cases(),
                                           *object_state_cases(), *independent_v3_cases(),
                                           *constructor_cases(), *independent_v4_cases())]
    (HERE / "v5-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps([(r["case"], r["equal"],
                       {k: (v["missing"], v["extra"]) for k,v in r["differences"].items()},
                       r["directional"]["analyzed_outer_sites"],
                       r["directional"]["summary_cost"])
                      for r in results], indent=2))
