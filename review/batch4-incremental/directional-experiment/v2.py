"""Second bounded scheduler: real old/new return-value resolutions before selection."""
import ast
import importlib.util
import json
from collections import defaultdict, deque
from pathlib import Path

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


def schedule(before, after, old):
    global last_summary_cost
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    ids = {n["node_id"]: n for n in old["nodes"]}
    old_g, old_a = catalog(before)
    new_g, new_a = catalog(after)
    callers, callees = defaultdict(set), defaultdict(set)
    for e in old["edges"]:
        if e["kind"] == "CALLS" and e["source"] in ids and e["target"] in ids:
            callers[e["target"]].add(e["source"])
            callees[e["source"]].add(e["target"])
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
            oldf, newf = v1.direct_functions(before.get(path)), v1.direct_functions(after.get(path))
            if path not in before or path not in after or set(oldf) != set(newf):
                selected.update(v1.static_importers(before, v1.module_name(path)))
                selected.update(v1.static_importers(after, v1.module_name(path)))
                events.append((path, "module-boundary/importers"))
            for name in oldf.keys() & newf.keys():
                ident = next((i for i, n in ids.items() if n["path"] == path
                              and n["qualname"] == name and n["kind"] == "function"), None)
                if ident is None:
                    continue
                old_value = summary("old", path, name)
                new_value = summary("new", path, name)
                # Literal/container payloads can be semantically relevant even
                # when both resolutions have no callable atoms.
                if old_value != new_value or v1.returns(oldf[name]) != v1.returns(newf[name]):
                    return_queue.append(ident)
                    events.append((path, name + ":resolved-return-change"))
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
                        fn = v1.direct_functions((before if node["path"] in before else after)
                                                  .get(node["path"])).get(node["qualname"].split(".")[-1])
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
                name = ids[caller]["qualname"].split(".")[-1]
                # Follow actual changed return summaries, including forwarding
                # through a local binding; finite graph worklist, each ID once.
                if summary("old", path, name) != summary("new", path, name):
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


if __name__ == "__main__":
    v1.schedule = schedule
    results = [run_case(*case) for case in (*v1.cases(), *independent_cases(), *transitive_local_case())]
    (HERE / "v2-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps([(r["case"], r["equal"],
                       {k: (v["missing"], v["extra"]) for k,v in r["differences"].items()},
                       r["directional"]["analyzed_outer_sites"],
                       r["directional"]["summary_cost"])
                      for r in results], indent=2))
