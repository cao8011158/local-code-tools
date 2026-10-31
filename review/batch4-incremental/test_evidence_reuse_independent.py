"""Independent boundary checks for typed evidence rebinding, not scheduler soundness."""
import importlib.util
from copy import deepcopy
from pathlib import Path

from lct.evidence_reuse import RebindContext
from lct.extract import python_nodes

HERE = Path(__file__).parent / "directional-experiment"


def load_v5():
    spec = importlib.util.spec_from_file_location("root_v5", HERE / "v5.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.v1.schedule = module.schedule
    return module


def test_tampered_old_proof_recomputes_owner_and_preserves_old_snapshot():
    m = load_v5()
    _, before, after = next(c for c in m.constructor_cases()
                            if c[0] == "same_named_initializers_isolated")
    old = m.v1.local.build(before)
    byid = {n["node_id"]: n for n in old["nodes"]}
    count = 0

    def corrupt(value):
        nonlocal count
        if isinstance(value, list):
            for item in value:
                corrupt(item)
        elif isinstance(value, dict):
            if "version_id" in value:
                value["version_id"] = "corrupt-old-stamp"
                count += 1
            for item in value.values():
                corrupt(item)

    for site in old["info"]["sites"]:
        if byid[site["execution_owner"]]["path"] == "src/c.py":
            corrupt(site)
    assert count > 0
    preserved = deepcopy(old)
    result, costs = m.candidate(before, after, old)
    assert "src/c.py" in costs["rejected_owner_paths"]
    assert old == preserved
    full = m.v1.local.build(after)
    assert m.v1.local.normalized(result) == m.v1.local.normalized(full)


def test_same_path_and_name_in_two_repositories_do_not_collide():
    old, new, ot, nt = {}, {}, {}, {}
    for repo in ("left", "right"):
        for nodes, trees, text in ((old, ot, "def f(): pass\ndef other(): return 1\n"),
                                   (new, nt, "def f(): pass\ndef other(): return 2\n")):
            group, parsed = python_nodes(dict(repository=repo, path="src/a.py",
                                               text=text, is_test=False))
            nodes.update({n["node_id"]: n for n in group})
            trees.update(parsed)
    ctx = RebindContext(old_nodes=old, new_nodes=new, old_trees=ot,
                        new_trees=nt, selected_paths=set())
    for ident, node in old.items():
        if node["qualname"] == "f":
            out = ctx.rebind({"definitions": [{"target": ident, "version_id": node["version_id"]}]},
                             owner_id=ident)
            assert out["definitions"][0] == {"target": ident, "version_id": new[ident]["version_id"]}


def test_unrelated_growth_does_not_grow_per_record_definition_checks():
    def measure(noise):
        old, ot = python_nodes(dict(repository="repo", path="a.py", text="def f(): pass\n",
                                    is_test=False))
        old = {n["node_id"]: n for n in old}
        new = deepcopy(old)
        ident = next(k for k, n in old.items() if n["qualname"] == "f")
        new[ident]["version_id"] = "new-capture"
        for i in range(noise):
            n = dict(old[ident], node_id=f"noise-{i}", path=f"noise_{i}.py")
            old[n["node_id"]] = n
            new[n["node_id"]] = dict(n)
        ctx = RebindContext(old_nodes=old, new_nodes=new, old_trees=ot,
                            new_trees=deepcopy(ot), selected_paths=set())
        record = {"definitions": [{"target": ident, "version_id": old[ident]["version_id"]}]}
        for _ in range(10):
            assert ctx.rebind(record, owner_id=ident)["definitions"][0]["version_id"] == "new-capture"
        return ctx.match_evaluations
    assert measure(0) == measure(1000) == 1
