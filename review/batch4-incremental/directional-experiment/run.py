"""Research-only selective call-site scheduler against the real Graph.build path.

The complete AST catalog and all non-CALLS relation passes are still rebuilt.
Only Graph.build's outer site iteration is restricted; Analyzer retains its full
site pool for recursive association. This is *not* a production incremental engine.
"""
import ast
import importlib.util
import inspect
import json
import textwrap
from collections import Counter, defaultdict, deque
from pathlib import Path

from lct.extract import module_name

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("local_harness", HERE.parent / "local-diff-experiment" / "run.py")
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)
GRAPH_SPEC = importlib.util.spec_from_file_location("lct._directional_graph_under_test", HERE / "graph_under_test.py")
graph_module = importlib.util.module_from_spec(GRAPH_SPEC)
GRAPH_SPEC.loader.exec_module(graph_module)
local.Graph = graph_module.Graph


def selective_build(sources, selected):
    """Use Graph.build verbatim except its outer site iteration guard."""
    nodes, trees = local.capture(sources)
    source = textwrap.dedent(inspect.getsource(graph_module.Graph.build))
    needle = "for item in analyzer.sites:\n"
    assert source.count(needle) == 1
    source = source.replace(needle, needle +
                            '            if self.nodes[item["execution_owner"]]["path"] not in self.selected: continue\n')
    namespace = dict(vars(graph_module))
    exec(source, namespace)
    class SelectiveGraph(graph_module.Graph):
        build = namespace["build"]
    graph = SelectiveGraph(nodes, trees, [local.REPO])
    graph.selected = selected
    edges, info = graph.build()
    return dict(nodes=nodes, edges=edges, info=info)


def direct_functions(source):
    if source is None:
        return {}
    tree = ast.parse(source)
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def returns(fn):
    if fn is None:
        return None
    return [ast.dump(x.value, include_attributes=False) if x.value else "bare"
            for x in ast.walk(fn) if isinstance(x, ast.Return)]


def call_arguments(fn):
    if fn is None:
        return None
    return [(ast.dump(c.func, include_attributes=False),
             [ast.dump(a, include_attributes=False) for a in c.args])
            for c in ast.walk(fn) if isinstance(c, ast.Call)]


def invokes_parameter(fn):
    if fn is None:
        return False
    names = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
    return any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in names
               for x in ast.walk(fn))


def static_importers(sources, module):
    return {p for p, source in sources.items() if module in local.imports(source, p)}


def schedule(before, after, old):
    """Whitelisted directional events from old relations and changed source AST only."""
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    ids = {n["node_id"]: n for n in old["nodes"]}
    callers = defaultdict(set)
    callees = defaultdict(set)
    for e in old["edges"]:
        if e["kind"] == "CALLS" and e["source"] in ids and e["target"] in ids:
            callers[e["target"]].add(e["source"])
            callees[e["source"]].add(e["target"])
    old_fn_id = {(n["path"], n["qualname"]): n["node_id"] for n in old["nodes"]
                 if n["kind"] == "function"}
    selected = set(changed)
    events = []
    returns_queue = deque()
    for path in sorted(changed):
        oldf, newf = direct_functions(before.get(path)), direct_functions(after.get(path))
        if path not in before or path not in after or set(oldf) != set(newf):
            selected.update(static_importers(after, module_name(path)))
            selected.update(static_importers(before, module_name(path)))
            events.append((path, "module-boundary/importers"))
        for name in oldf.keys() & newf.keys():
            node_id = old_fn_id.get((path, name))
            if node_id is None:
                continue
            if returns(oldf[name]) != returns(newf[name]):
                returns_queue.append(node_id)
                events.append((path, name + ":return-expression"))
            if call_arguments(oldf[name]) != call_arguments(newf[name]):
                for callee in callees[node_id]:
                    if invokes_parameter(oldf.get(ids[callee]["qualname"].split(".")[-1])
                                         if ids[callee]["path"] == path else
                                         direct_functions(before.get(ids[callee]["path"]))
                                         .get(ids[callee]["qualname"].split(".")[-1])):
                        selected.add(ids[callee]["path"])
                events.append((path, name + ":call-arguments"))
    visited = set()
    while returns_queue:
        target = returns_queue.popleft()
        if target in visited:
            continue
        visited.add(target)
        for caller in callers[target]:
            selected.add(ids[caller]["path"])
            # A caller forwarding a changed return may alter its consumers too.
            fn = direct_functions(before.get(ids[caller]["path"])).get(ids[caller]["qualname"].split(".")[-1])
            if fn and any(isinstance(x.value, ast.Call) for x in ast.walk(fn)
                          if isinstance(x, ast.Return)):
                returns_queue.append(caller)
    return selected & set(after), events


def candidate(before, after, old):
    selected, events = schedule(before, after, old)
    partial = selective_build(after, selected)
    old_ids = {n["node_id"]: n["path"] for n in old["nodes"]}
    new_ids = {n["node_id"]: n["path"] for n in partial["nodes"]}
    # All nodes and non-call relations came from the new full context pass.
    edges = [e for e in partial["edges"] if e["kind"] != "CALLS" or
             new_ids.get(e["source"]) in selected]
    edges += [e for e in old["edges"] if e["kind"] == "CALLS" and
              old_ids.get(e["source"]) not in selected and old_ids.get(e["source"]) in after]
    sites = partial["info"]["sites"] + [s for s in old["info"]["sites"]
                                         if old_ids.get(s["execution_owner"]) not in selected
                                         and old_ids.get(s["execution_owner"]) in after]
    return dict(nodes=partial["nodes"], edges=edges, info=dict(sites=sites)), dict(
        selected=sorted(selected), events=events,
        analyzed_outer_sites=partial["info"]["call_sites"],
        actual_jedi_queries=partial["info"]["jedi_queries_executed"],
        association_evaluations=partial["info"]["association_evaluations"],
        full_ast_context_files=len(after), non_call_relation_pass="all files")


def run_case(name, before, after):
    old = local.build(before)
    result, cost = candidate(before, after, old)
    component_result, component_cost = local.candidate(before, after, old)
    full = local.build(after)  # comparison only, never used by schedule/candidate
    a, b = local.normalized(result), local.normalized(full)
    diffs = {}
    for kind in a:
        aa, bb = Counter(a[kind]), Counter(b[kind])
        if aa != bb:
            diffs[kind] = dict(missing=sum((bb-aa).values()), extra=sum((aa-bb).values()),
                               missing_examples=list((bb-aa).elements())[:2],
                               extra_examples=list((aa-bb).elements())[:2])
    component_equal = local.normalized(component_result) == b
    return dict(case=name, equal=not diffs, differences=diffs, directional=cost,
                component=dict(equal=component_equal,
                               parsed_file_attempts=component_cost["parsed_file_attempts"],
                               sites=component_cost["analyzed_sites"],
                               actual_jedi_queries=component_cost["jedi_queries_executed"]),
                full=dict(files=len(after), sites=full["info"]["call_sites"],
                          actual_jedi_queries=full["info"]["jedi_queries_executed"],
                          association_evaluations=full["info"]["association_evaluations"]))


def cases():
    hub = {"src/hub.py": "def helper():\n x = 1\n return None\n"}
    hub.update({f"src/user_{i}.py": f"from hub import helper\ndef user_{i}(): helper()\n"
                for i in range(20)})
    yield "shared_helper_unused_local", hub, {**hub, "src/hub.py": "def helper():\n x = 2\n return None\n"}
    callback = {"src/callee.py": "def invoke(cb): cb()\n",
                "src/caller.py": "from callee import invoke\ndef first(): pass\ndef second(): pass\ndef run(): invoke(first)\n"}
    yield "callback_argument", callback, {**callback, "src/caller.py": callback["src/caller.py"].replace("invoke(first)", "invoke(second)")}
    receiver = {"src/maker.py": "class One:\n def alpha(self): pass\nclass Two:\n def beta(self): pass\ndef make(): return One()\n",
                "src/use.py": "from maker import make\ndef run(): make().alpha()\n"}
    yield "return_object_receiver", receiver, {**receiver, "src/maker.py": receiver["src/maker.py"].replace("return One()", "return Two()")}
    body = {"src/a.py": "def work():\n x = 1\n return None\n", "src/b.py": "from a import work\ndef f(): work()\n"}
    yield "body_unused_literal", body, {**body, "src/a.py": body["src/a.py"].replace("x = 1", "x = 2")}
    yield "deletion", body, {"src/b.py": body["src/b.py"]}
    absent = {"src/b.py": "from newmod import work\ndef f(): work()\n"}
    yield "new_absent_module", absent, {**absent, "src/newmod.py": "def work(): pass\n"}
    chain = {"src/a.py": "class One:\n def alpha(self): pass\nclass Two:\n def beta(self): pass\ndef make(): return One()\n",
             "src/b.py": "from a import make\ndef forward(): return make()\n",
             "src/c.py": "from b import forward\ndef consume(): forward().alpha()\n"}
    yield "connected_transitive_return", chain, {**chain, "src/a.py": chain["src/a.py"].replace("return One()", "return Two()")}
    cycle = {"src/a.py": "from b import b\ndef a():\n b()\n return None\n",
             "src/b.py": "from a import a\ndef b():\n a()\n return None\n"}
    yield "cycle_termination", cycle, {**cycle, "src/a.py": cycle["src/a.py"].replace("return None", "return 1")}
    through_local = {"src/a.py": "class One:\n def alpha(self): pass\nclass Two:\n def beta(self): pass\ndef make():\n x = One()\n return x\n",
                     "src/b.py": "from a import make\ndef use(): make().alpha()\n"}
    yield "unsupported_return_through_local", through_local, {**through_local,
          "src/a.py": through_local["src/a.py"].replace("x = One()", "x = Two()")}
    kw = {"src/a.py": "def invoke(cb): cb()\n",
          "src/b.py": "from a import invoke\ndef first(): pass\ndef second(): pass\ndef use(): invoke(cb=first)\n"}
    yield "unsupported_keyword_callback", kw, {**kw, "src/b.py": kw["src/b.py"].replace("cb=first", "cb=second")}
    selector = {"src/a.py": "def selector(): return 'one'\n",
                "src/b.py": "from a import selector\ndef one(): pass\ndef two(): pass\nhandlers = {'one': one, 'two': two}\ndef use(): handlers[selector()]()\n"}
    yield "selector_literal_changes_target", selector, {**selector,
          "src/a.py": selector["src/a.py"].replace("'one'", "'two'")}


def main():
    results = [run_case(*case) for case in cases()]
    (HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps([{k: r[k] for k in ("case", "equal", "directional", "component", "full")}
                      | {"difference_counts": {k: (v["missing"], v["extra"])
                                               for k, v in r["differences"].items()}}
                      for r in results], indent=2))


if __name__ == "__main__":
    main()
