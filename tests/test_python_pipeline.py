"""Phase-one semantic contract. Sources are captured, never imported."""

import json
from pathlib import Path

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph


def analyze(tmp_path, sources, closed=True):
    nodes, trees = [], {}
    for path, text in sources.items():
        f = dict(repository="fixture", path=path, text=text, is_test=False, sha256=digest(text))
        ns, ts = python_nodes(f)
        nodes.extend(ns)
        trees.update(ts)
    g = Graph(
        nodes,
        trees,
        [dict(name="fixture", path=str(tmp_path), head="captured", status="", closed_world=closed)],
    )
    edges, info = g.build()
    return nodes, edges, info


def site(result, expression, owner, line=None):
    nodes, edges, info = result
    byid = {n["node_id"]: n for n in nodes}
    matches = [
        s
        for s in info["sites"]
        if s["expression"] == expression
        and byid[s["execution_owner"]]["qualname"] == owner
        and (line is None or s["line"] == line)
    ]
    assert len(matches) == 1, (expression, owner, matches)
    s = matches[0]
    s["names"] = {byid[t]["qualname"] for t in s["targets"] if t in byid}
    for e in edges:
        if e.get("site_id") == s["site_id"]:
            assert e["source"] == s["execution_owner"]
    return s


def expect(result, expression, owner, targets, *, unknown=False, complete=True, forbidden=()):
    s = site(result, expression, owner)
    assert s["names"] == set(targets)
    assert not s["names"].intersection(forbidden)
    assert s["unknown_origin"] is unknown
    assert s["complete"] is complete
    assert s["evidence"]
    assert s["line"] > 0 and s["end_column"] > s["column"]
    return s


def test_identity_spans_versions_and_lambda(tmp_path):
    text = "def f():\n def x(): pass\n return x\ndef f():\n def x(): pass\na,b = (lambda: 1), (lambda: 2)\n"
    nodes, _, _ = analyze(tmp_path, {"src/demo.py": text})
    assert len(nodes) == len({n["node_id"] for n in nodes})
    assert len(nodes) == len({n["version_id"] for n in nodes})
    lambdas = [n for n in nodes if n["node_type"] == "lambda"]
    assert len(lambdas) == 2 and lambdas[0]["column"] != lambdas[1]["column"]
    shifted, _, _ = analyze(tmp_path, {"src/demo.py": "\n" + text})
    assert [n["logical_id"] for n in nodes] == [n["logical_id"] for n in shifted]
    assert all(a["version_id"] != b["version_id"] for a, b in zip(nodes, shifted))
    for n in nodes:
        assert n["repository_id"] and n["snapshot_id"] and n["fingerprint"]
        assert n["definition_line"] >= 1 and n["end_column"] >= 0


def test_imports_src_relative_and_reexport(tmp_path):
    r = analyze(
        tmp_path,
        {
            "src/pkg/__init__.py": "from .impl import work as run\n",
            "src/pkg/impl.py": "def work(): pass\n",
            "src/pkg/client.py": "from . import run as alias\ndef caller(): alias()\n",
        },
    )
    expect(r, "alias", "caller", {"work"})
    assert any(e["kind"] == "IMPORTS" for e in r[1])


def test_overwrite_branch_and_python_scope(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
def work(): pass
def overwrite():
 cb=a
 cb=b
 cb()
def branch(flag):
 if flag: cb=a
 else: cb=b
 cb()
def unbound():
 work()
 work=b
class C:
 def ghost(self): pass
 def caller(self): ghost()
 def run(self): pass
 run=b
def driver(): C().run()
"""
        },
    )
    expect(r, "cb", "overwrite", {"b"}, forbidden={"a"})
    expect(r, "cb", "branch", {"a", "b"})
    expect(r, "work", "unbound", set(), forbidden={"work"})
    expect(r, "ghost", "C.caller", set(), forbidden={"C.ghost"})
    expect(r, "C().run", "driver", {"b"}, forbidden={"C.run"})


def test_bound_receiver_static_class_and_super(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def target(): pass
class Base:
 def run(self): pass
class C(Base):
 def invoke(self, cb): cb()
 @staticmethod
 def static(cb): cb()
 @classmethod
 def construct(cls): return cls()
 def run(self): super().run()
def driver():
 obj=C()
 callback=obj.invoke
 callback(target)
 C.static(target)
 C.construct()
"""
        },
    )
    expect(r, "cb", "C.invoke", {"target"})
    expect(r, "cb", "C.static", {"target"})
    expect(r, "callback", "driver", {"C.invoke"})
    expect(r, "C.construct", "driver", {"C.construct"})
    expect(r, "super().run", "C.run", {"Base.run"})


def test_containers_registry_and_no_reference_calls(tmp_path):
    r = analyze(
        tmp_path,
        {
            "src/registry.py": "handlers={}\ndef register(key,cb): handlers[key]=cb\n",
            "src/demo.py": """from registry import register,handlers
def a(): pass
def b(): pass
register('go',a)
def dispatch(k):
 table={'a':a,'b':b}
 table['a']()
 table[k]()
 values=[a,b]
 values[1]()
 values[k]()
 handlers['go']()
def references():
 cb=a
 refs=[a,b]
 return b
""",
        },
    )
    expect(r, "table['a']", "dispatch", {"a"}, forbidden={"b"})
    expect(r, "table[k]", "dispatch", {"a", "b"})
    expect(r, "values[1]", "dispatch", {"b"}, forbidden={"a"})
    expect(r, "values[k]", "dispatch", {"a", "b"})
    expect(r, "handlers['go']", "dispatch", {"a"})
    assert not any(s for s in r[2]["sites"] if s["expression"] in ("a", "b"))
    byid = {n["node_id"]: n["qualname"] for n in r[0]}
    assert {
        byid[e["target"]]
        for e in r[1]
        if e["kind"] == "REFERENCES" and byid[e["source"]] == "references"
    } == {"a", "b"}


def test_known_mixed_and_open_callbacks(tmp_path):
    text = """def target(): pass
def invoke(cb): cb()
def mixed(cb): cb()
def driver(unknown):
 invoke(target)
 mixed(target)
 mixed(unknown)
"""
    r = analyze(tmp_path, {"demo.py": text})
    expect(r, "cb", "invoke", {"target"})
    expect(r, "cb", "mixed", {"target"}, unknown=True, complete=False)
    r = analyze(tmp_path, {"demo.py": text}, closed=False)
    expect(r, "cb", "invoke", {"target"}, unknown=True, complete=False)


def test_returns_chains_with_and_async_with(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def target(): pass
class C:
 def work(self): pass
 def chain(self): return self
 def __enter__(self): return self
 def __exit__(self,*args): pass
 async def __aenter__(self): return self
 async def __aexit__(self,*args): pass
def factory(): return target
def object_factory(): return C()
def driver():
 factory()()
 object_factory().chain().work()
 with C() as obj: obj.work()
async def async_driver():
 async with C() as obj: obj.work()
"""
        },
    )
    expect(r, "factory()", "driver", {"target"})
    expect(r, "object_factory().chain().work", "driver", {"C.work"})
    for owner, syntax in (("driver", "With"), ("async_driver", "AsyncWith")):
        s = expect(r, "obj.work", owner, {"C.work"}, unknown=True, complete=False)
        assert s["phase"] == "body"
        assert any(
            c["event_kind"] == "region"
            and c["syntax"] == syntax
            and c["outcome"] == "UNKNOWN_EFFECT"
            and c["reason"] == "unsupported-protocol-region"
            for c in s["resolution_decision"]["write_source_coverage"]["checks"]
        )


def test_execution_ownership_defaults_decorators_annotations(tmp_path):
    text = """def target(): pass
def make(): return int
def decorate(fn): return fn
@decorate
def outer(x=make(), y: make()=None) -> make():
 def inner(): target()
 value=lambda: target()
 return value
"""
    r = analyze(tmp_path, {"demo.py": text})
    inner = expect(r, "target", "outer.inner", {"target"})
    lam = expect(r, "target", "outer.<lambda>", {"target"})
    assert inner["execution_owner"] != lam["execution_owner"]
    makes = [s for s in r[2]["sites"] if s["expression"] == "make"]
    assert len(makes) == 3
    byid = {n["node_id"]: n for n in r[0]}
    assert all(byid[s["execution_owner"]]["node_type"] == "module" for s in makes)
    assert {s["phase"] for s in makes} == {"definition", "annotation"}
    assert all(byid[s["lexical_owner"]]["qualname"] == "outer" for s in makes)
    deco = expect(r, "decorate", "demo", {"decorate"})
    assert deco["kind"] == "implicit_decorator" and deco["phase"] == "definition"
    deferred = analyze(tmp_path, {"demo.py": "from __future__ import annotations\n" + text})
    assert len([s for s in deferred[2]["sites"] if s["expression"] == "make"]) == 1


FROZEN_ROOT = Path(__file__).resolve().parents[1] / "experiments/python_graph"
FROZEN_CALLS = [
    s
    for s in json.loads((FROZEN_ROOT / "truth.json").read_text())["sites"]
    if s["kind"] != "reference"
]


@pytest.fixture(scope="module")
def frozen_result(tmp_path_factory):
    root = FROZEN_ROOT
    sources = {"src/" + p.name: p.read_text() for p in (root / "fixtures").glob("*.py")}
    return analyze(tmp_path_factory.mktemp("frozen"), sources)


@pytest.mark.parametrize("expected", FROZEN_CALLS, ids=lambda s: s["id"])
def test_frozen_answer_semantics(frozen_result, expected):
    r = frozen_result
    sources = {"src/" + p.name: p.read_text() for p in (FROZEN_ROOT / "fixtures").glob("*.py")}
    byid = {n["node_id"]: n for n in r[0]}

    def label(ident):
        n = byid[ident]
        mod = Path(n["path"]).stem
        return mod + ":" + ("<module>" if n["node_type"] == "module" else n["qualname"])

    lines = sources["src/" + expected["file"]].splitlines()
    line = next(i + 1 for i, t in enumerate(lines) if "case:" + expected["id"] in t)
    matches = [
        s
        for s in r[2]["sites"]
        if byid[s["execution_owner"]]["path"] == "src/" + expected["file"]
        and s["line"] == line
        and (not expected["expression"] or s["expression"] == expected["expression"])
    ]
    assert len(matches) == 1, expected["id"]
    s = matches[0]
    actual = {label(t) for t in s["targets"] if t in byid}
    external = {e["full_name"].replace("json.loads", "json:loads") for e in s["boundaries"]}
    assert actual | external == set(expected["targets"]), (expected["id"], s)
    assert not actual.intersection(expected["forbidden"])
    assert label(s["execution_owner"]) == expected["context"]
    assert s["phase"] == expected["phase"]
    assert s["complete"] == expected["complete"], expected["id"]
    assert s["unknown_origin"] is (not expected["complete"])


def test_registry_key_correlation_and_bound_method_negative(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """handlers={}
def register(key,cb): handlers[key]=cb
def a(): pass
def b(): pass
register("a",a)
register("b",b)
def dispatch(): handlers["a"]()
class C:
 def invoke(self,cb): cb()
def caller():
 method=C().invoke
 method(a)
"""
        },
    )
    expect(r, "handlers['a']", "dispatch", {"a"}, forbidden={"b"})
    expect(r, "cb", "C.invoke", {"a"}, forbidden={"C", "C.invoke", "b"})


def test_same_line_and_nested_shadowing(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
def driver(): cb=a; cb=b; cb()
def outer():
 def a(): pass
 def inner(): a()
 inner()
"""
        },
    )
    expect(r, "cb", "driver", {"b"}, forbidden={"a"})
    expect(r, "a", "outer.inner", {"outer.a"}, forbidden={"a"})


def test_explicit_boundary_and_tool_failure(tmp_path, monkeypatch):
    import jedi

    r = analyze(tmp_path, {"demo.py": "import json\ndef caller(): json.loads('{}')\n"})
    s = expect(r, "json.loads", "caller", set())
    assert s["boundaries"] == [dict(full_name="json.loads", reason="external-or-excluded")]
    (tmp_path / "excluded.py").write_text("def work(): pass\n", encoding="utf-8")
    r = analyze(tmp_path, {"demo.py": "from excluded import work\ndef caller(): work()\n"})
    s = expect(r, "work", "caller", set(), unknown=True, complete=False)
    assert s["unresolved_reasons"]

    def failed(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(jedi.Script, "infer", failed)
    r = analyze(tmp_path, {"demo.py": "def caller(obj): obj.work()\n"})
    s = expect(r, "obj.work", "caller", set(), unknown=True, complete=False)
    assert any(reason.startswith("jedi-error:") for reason in s["unresolved_reasons"])


def test_exact_mapping_without_full_name_unicode_and_ambiguity(tmp_path):
    from types import SimpleNamespace

    from lct.python_analysis import Analyzer

    text = "def 工作(): pass\nclass C:\n def method(self): pass\n"
    ns, ts = python_nodes(dict(text=text, path="demo.py", repository="fixture", is_test=False))
    g = Graph(ns, ts, [dict(name="fixture", path=str(tmp_path), head="test")])
    a = Analyzer(g.nodes, ts, g.repos, g.imported)
    try:
        path = next(iter(a.paths))
        name = SimpleNamespace(
            name="工作", full_name=None, type="function", line=1, column=4, module_path=path
        )
        value, raw = a.map_name(name)
        assert {g.nodes[v.target]["qualname"] for v in value.atoms} == {"工作"}
        assert raw["mapping"] == "exact-captured-definition"
        name.module_path = None
        value, raw = a.map_name(name)
        assert not value.atoms and value.unknown
        assert raw["mapping"] == "unlocatable-jedi-result"
        name.module_path = path
        name.column = 5
        value, raw = a.map_name(name)
        assert not value.atoms and value.unknown
        name.column = 4
        duplicate = dict(ns[1], node_id="ambiguous")
        a.nodes["ambiguous"] = duplicate
        a.trees["ambiguous"] = ts[ns[1]["node_id"]]
        a.module_for["ambiguous"] = ns[0]["node_id"]
        value, raw = a.map_name(name)
        assert not value.atoms and value.unknown
        assert raw["mapping"] == "ambiguous-captured-definition"
        assert any(n["node_type"] == "method" for n in ns)
    finally:
        a.close()


def test_callback_passthrough_and_unknown_forwarding(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def target(): pass
def sink(cb): cb()
def middle(cb): sink(cb)
def driver(unknown):
 middle(target)
 middle(unknown)
"""
        },
    )
    expect(r, "cb", "sink", {"target"}, unknown=True, complete=False)


def test_unknown_container_mutation_is_not_complete(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def caller(unknown):
 table={"a":a}
 table.update(unknown)
 table["a"]()
"""
        },
    )
    expect(r, "table['a']", "caller", {"a"}, unknown=True, complete=False)


def test_unconditional_container_slot_replacement(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
def caller():
 table={"a":a}
 table["a"]=b
 table["a"]()
"""
        },
    )
    expect(r, "table['a']", "caller", {"b"}, forbidden={"a"})


def test_inherited_classmethod_receiver(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """class Base:
 @classmethod
 def construct(cls): return cls()
 def work(self): pass
class Child(Base):
 def work(self): pass
def caller(): Child.construct().work()
"""
        },
    )
    expect(r, "Child.construct().work", "caller", {"Child.work"}, forbidden={"Base.work"})


def test_callback_default_and_keyword_only(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def target(): pass
def invoke(cb=target): cb()
def kw(*,cb=target): cb()
def caller():
 invoke()
 kw()
"""
        },
    )
    expect(r, "cb", "invoke", {"target"})
    expect(r, "cb", "kw", {"target"})


def test_unmodeled_decorator_replacement_is_explicit(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def other(): pass
def replace(fn): return other
@replace
def original(): pass
def caller(): original()
"""
        },
    )
    s = expect(r, "original", "caller", {"other"}, unknown=True, complete=False, forbidden={"original"})
    assert "decorated-binding-not-modeled" in s["unresolved_reasons"]
