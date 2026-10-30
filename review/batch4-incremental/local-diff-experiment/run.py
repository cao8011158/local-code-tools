"""Bounded local-diff feasibility experiment; no production writes or services."""
import ast
import json
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict, deque
from pathlib import Path

from lct.extract import python_nodes, module_name
from lct.graph import Graph


HERE = Path(__file__).resolve().parent
REPO = dict(name="fixture", path="/nonexistent/lct-fixture", head="captured", closed_world=True)


def capture(sources):
    nodes, trees = [], {}
    for path, source in sorted(sources.items()):
        ns, ts = python_nodes(dict(repository="fixture", path=path, text=source,
                                   is_test=False))
        nodes.extend(ns)
        trees.update(ts)
    return nodes, trees


def build(sources):
    nodes, trees = capture(sources)
    edges, info = Graph(nodes, trees, [REPO]).build()
    return dict(nodes=nodes, edges=edges, info=info)


def imports(source, path):
    """Cheap capture inventory, not semantic analysis or a new-state oracle."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    current = module_name(path)
    package = current.split(".") if path.endswith("/__init__.py") else current.split(".")[:-1]
    names = set()
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            names.update(a.name for a in item.names)
        elif isinstance(item, ast.ImportFrom):
            if item.level:
                prefix = package[:len(package) - item.level + 1]
                base = ".".join(prefix + ([item.module] if item.module else []))
            else:
                base = item.module or ""
            if base:
                names.add(base)
                names.update(base + "." + a.name for a in item.names)
    return names


def file_index(old):
    """Both directions of genuine cross-file relations, indexed by file."""
    db = sqlite3.connect(":memory:")
    db.execute("create table adjacency(src text, dst text, kind text)")
    db.execute("create index by_src on adjacency(src)")
    db.execute("create index by_dst on adjacency(dst)")
    byid = {n["node_id"]: n["path"] for n in old["nodes"]}
    # An unresolved named import has a boundary source on LOOKUP_IN. Its owner
    # comes from the matching IMPORTS edge; other shared boundaries are not links.
    boundary_owners = defaultdict(set)
    for e in old["edges"]:
        if e["kind"] == "IMPORTS" and e["target"] and e["target"].startswith("boundary:unresolved-import:"):
            if e["source"] in byid:
                boundary_owners[e["target"]].add(byid[e["source"]])
    rows = set()
    for e in old["edges"]:
        if e["kind"] == "CONTAINS":
            continue
        src = {byid[e["source"]]} if e["source"] in byid else boundary_owners[e["source"]] if e["kind"] == "LOOKUP_IN" else set()
        dst = {byid[e["target"]]} if e["target"] in byid else boundary_owners[e["target"]] if e["kind"] == "IMPORTS" else set()
        rows.update((a, b, e["kind"]) for a in src for b in dst if a != b)
    db.executemany("insert into adjacency values(?,?,?)", sorted(rows))
    return db


def closure(db, seeds):
    seen = set(seeds)
    queue = deque(seeds)
    while queue:
        path = queue.popleft()
        for (neighbor,) in db.execute("select dst from adjacency where src=? union select src from adjacency where dst=?", (path, path)):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def candidate(old_sources, new_sources, old):
    changed = {p for p in old_sources.keys() | new_sources.keys()
               if old_sources.get(p) != new_sources.get(p)}
    db = file_index(old)
    # Source/path inventory is cheap but global: count it separately below.
    modules = defaultdict(set)
    for p in new_sources:
        modules[module_name(p)].add(p)
    touched = set(changed)
    rounds, executed, sites, parsed, import_parses = [], 0, 0, 0, 0
    partial = None
    for _ in range(len(new_sources) + 2):
        expanded = closure(db, touched)
        scanned = set()
        while True:
            pending = sorted((expanded & new_sources.keys()) - scanned)
            if not pending:
                break
            for p in pending:
                scanned.add(p)
                import_parses += 1
                for name in imports(new_sources[p], p):
                    expanded.update(modules.get(name, ()))
            expanded = closure(db, expanded)
        included = expanded & new_sources.keys()
        partial = build({p: new_sources[p] for p in sorted(included)})
        parsed += len(included)
        executed += partial["info"]["jedi_queries_executed"]
        sites += partial["info"]["call_sites"]
        rounds.append(dict(files=sorted(included), sites=partial["info"]["call_sites"],
                           jedi=partial["info"]["jedi_queries_executed"]))
        pbyid = {n["node_id"]: n["path"] for n in partial["nodes"]}
        discovered = {pbyid[e["target"]] for e in partial["edges"]
                      if e["target"] in pbyid and e["source"] in pbyid
                      and pbyid[e["source"]] != pbyid[e["target"]]}
        new_touched = expanded | discovered
        if new_touched == touched or (new_touched & new_sources.keys()) == included:
            break
        touched = new_touched
    oldpaths = {n["node_id"]: n["path"] for n in old["nodes"]}
    # Edges sourced in untouched files are reused. The LOOKUP_IN boundary owner
    # is resolved by the corresponding old import edge to keep graph ownership.
    old_boundaries = {e["target"]: oldpaths[e["source"]] for e in old["edges"]
                      if e["kind"] == "IMPORTS" and e["source"] in oldpaths
                      and e["target"] and e["target"].startswith("boundary:unresolved-import:")}
    def owner(e):
        if e["kind"] == "CONTAINS" and e["source"] == "fixture::repository":
            return oldpaths.get(e["target"])
        return oldpaths.get(e["source"], old_boundaries.get(e["source"]))
    reused_edges = [e for e in old["edges"] if owner(e) not in included
                    and owner(e) not in changed and owner(e) is not None
                    and oldpaths.get(e["target"]) not in changed]
    reused_sites = [s for s in old["info"]["sites"]
                    if oldpaths.get(s["execution_owner"]) not in included | changed]
    reused_nodes = [n for n in old["nodes"] if n["path"] not in included | changed]
    result = dict(nodes=reused_nodes + partial["nodes"], edges=reused_edges + partial["edges"],
                  info=dict(sites=reused_sites + partial["info"]["sites"]))
    return result, dict(changed=sorted(changed), rounds=rounds, parsed_file_attempts=parsed,
                        unique_parsed_files=len(included), examined_import_file_count=import_parses,
                        analyzed_sites=sites, jedi_queries_executed=executed,
                        preparatory_old_edges=len(old["edges"]),
                        preparatory_old_nodes=len(old["nodes"]),
                        preparatory_full_path_inventory=len(new_sources),
                        adjacency_rows=db.execute("select count(*) from adjacency").fetchone()[0])


def normalized(graph):
    byid = {n["node_id"]: n for n in graph["nodes"]}
    # Preserve meaningful metadata. Exclude capture/version and opaque site IDs,
    # which depend on snapshot IDs rather than semantic equivalence.
    node_keys = ("node_id", "path", "kind", "qualname", "parent", "start", "end", "column", "signature", "fingerprint")
    edge_keys = ("source", "target", "kind", "status", "basis", "line", "column", "expression", "complete", "unknown_origin", "target_role", "invocation_phase", "executes_body", "phase", "lookup_status", "unresolved_reasons", "lookup")
    site_keys = ("execution_owner", "kind", "line", "column", "expression", "targets", "unknown_origin", "complete", "completeness_basis", "resolution_kind", "resolution_decision", "unresolved_reasons", "boundaries")
    return {"nodes": sorted([json.dumps({k: n[k] for k in node_keys if k in n}, sort_keys=True) for n in graph["nodes"]]),
            "edges": sorted([json.dumps({k: e[k] for k in edge_keys if k in e}, sort_keys=True) for e in graph["edges"]]),
            "sites": sorted([json.dumps({k: s[k] for k in site_keys if k in s}, sort_keys=True) for s in graph["info"]["sites"]])}


def run_case(name, before, after):
    old = build(before)
    local, cost = candidate(before, after, old)
    full = build(after)  # Comparison oracle only; never passed to candidate.
    actual, expected = normalized(local), normalized(full)
    diffs = {}
    for kind in actual:
        a, e = Counter(actual[kind]), Counter(expected[kind])
        if a != e:
            diffs[kind] = dict(missing=sum((e-a).values()), extra=sum((a-e).values()),
                               missing_examples=sorted((e-a).elements())[:2], extra_examples=sorted((a-e).elements())[:2])
    return dict(case=name, equal=not diffs, differences=diffs, candidate=cost,
                full=dict(files=len(after), sites=full["info"]["call_sites"],
                          jedi_queries_executed=full["info"]["jedi_queries_executed"]))


def cases():
    base = {"src/a.py": "def a(): pass\n", "src/b.py": "from a import a\ndef b(): a()\n"}
    yield "direct_change", base, {**base, "src/a.py": "def a(): return 1\n"}
    yield "delete", base, {"src/b.py": base["src/b.py"]}
    b = {"src/a.py": "from b import B\ndef a(): return B()\n", "src/b.py": "class B:\n def run(self): pass\n", "src/c.py": "from a import a\ndef f(): a().run()\n"}
    yield "return_receiver_B", b, {**b, "src/b.py": "class B:\n def run(self): return 1\n"}
    c = {"src/a.py": "def a(cb): cb()\n", "src/b.py": "from a import a\ndef b(): pass\ndef other(): pass\ndef f(): a(b)\n"}
    yield "callback_A_to_B", c, {**c, "src/b.py": "from a import a\ndef b(): pass\ndef other(): pass\ndef f(): a(other)\n"}
    yield "missing_name_resolved", {"src/a.py": "pass\n", "src/b.py": "from a import work\ndef f(): work()\n"}, {"src/a.py": "def work(): pass\n", "src/b.py": "from a import work\ndef f(): work()\n"}
    absent = {"src/b.py": "from missing_mod import new_handler\ndef f(): new_handler()\n",
              "src/seed.py": "def seed(): pass\n"}
    yield "new_module_resolves_old_import", absent, {**absent, "src/missing_mod.py": "def new_handler(): pass\n"}
    d = {"src/a.py": "def work(): pass\n", "src/b.py": "def f(): pass\n"}
    yield "added_import_disconnected", d, {**d, "src/b.py": "from a import work\ndef f(): work()\n"}
    r = {"src/pkg/__init__.py": "from .impl import work as run\n", "src/pkg/impl.py": "def work(): pass\n", "src/pkg/client.py": "from . import run\ndef f(): run()\n"}
    yield "reexport", r, {**r, "src/pkg/impl.py": "def work(): return 1\n"}
    i = {"src/base.py": "class Base:\n def run(self): pass\n", "src/child.py": "from base import Base\nclass Child(Base): pass\ndef f(): Child().run()\n"}
    yield "inheritance", i, {**i, "src/base.py": "class Base:\n def run(self): return 1\n"}
    reg = {"src/a.py": "def handler(): pass\ndef alternate(): pass\nregistry = {'x': handler}\n", "src/b.py": "from a import registry\ndef f(): registry['x']()\n"}
    yield "registry", reg, {**reg, "src/a.py": "def handler(): pass\ndef alternate(): pass\nregistry = {'x': alternate}\n"}
    for count in (20, 100):
        noise = {f"src/noise_{k:03}.py": f"def z{k}(): pass\ndef f{k}(): z{k}()\n" for k in range(count)}
        before = {**base, **noise}
        yield f"unrelated_{count}", before, {**before, "src/a.py": "def a(): return 1\n"}
    dynamic = {"src/a.py": "def a(): pass\n", "src/b.py": "import a\ndef f(name): getattr(a, name)()\n"}
    yield "dynamic_unknown", dynamic, {**dynamic, "src/a.py": "def a(): return 1\n"}


def main():
    results = [run_case(*case) for case in cases()]
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps([dict(case=r["case"], equal=r["equal"], candidate=r["candidate"], full=r["full"],
                           difference_counts={k: (v["missing"], v["extra"]) for k,v in r["differences"].items()})
                      for r in results], indent=2))


if __name__ == "__main__":
    main()
