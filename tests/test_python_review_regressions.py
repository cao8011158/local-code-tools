"""Independent review counterexamples, authored before the repair; production inputs open."""

import pytest

from tests.test_python_pipeline import analyze, expect, site

CASES = [
    (
        "instance_override",
        """def target(): pass
class C:
 def __init__(self): self.run=target
 def run(self): pass
def caller(): C().run()
""",
        "C().run",
        "caller",
        {"target"},
        {"C.run"},
        False,
    ),
    (
        "default_lambda",
        """def target(): pass
def f(cb=lambda: target()):
 def target(): pass
 cb()
f()
""",
        "target",
        "f.<lambda>",
        {"target"},
        {"f.target"},
        False,
    ),
    (
        "named_expression",
        """def a(): pass
def caller():
 (cb:=a)
 cb()
""",
        "cb",
        "caller",
        {"a"},
        set(),
        False,
    ),
    (
        "deleted_slot",
        """def a(): pass
def caller():
 table={"x":a}
 del table["x"]
 table["x"]()
""",
        "table['x']",
        "caller",
        set(),
        {"a"},
        False,
    ),
    (
        "keyword_escape",
        """def a(): pass
def caller(modify):
 table={"x":a}
 modify(table=table)
 table["x"]()
""",
        "table['x']",
        "caller",
        {"a"},
        set(),
        True,
    ),
    (
        "negative_index",
        """def a(): pass
def b(): pass
def caller():
 table=[a,b]
 table[-1]()
""",
        "table[-1]",
        "caller",
        {"b"},
        {"a"},
        False,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_independent_review_open_world(tmp_path, case):
    label, source, expression, owner, targets, forbidden, unknown = case
    if label == "deleted_slot":
        targets, unknown = set(), True
    elif label == "keyword_escape":
        targets, unknown = {"a"}, False
    result = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = expect(
        result,
        expression,
        owner,
        targets,
        forbidden=forbidden,
        unknown=unknown,
        complete=not unknown,
    )
    byid = {n["node_id"]: n for n in result[0]}
    assert byid[s["lexical_owner"]]["qualname"] == owner
    assert s["phase"] == "body"
    assert (
        s["line"]
        == dict(
            instance_override=5,
            default_lambda=2,
            named_expression=4,
            deleted_slot=5,
            keyword_escape=5,
            negative_index=5,
        )[case[0]]
    )


def test_instance_field_precedence_boundaries(tmp_path):
    source = """def a(): pass
def b(): pass
class C:
 def __init__(self,cb): self.run=cb
 def run(self): pass
class Plain:
 def run(self): pass
def caller(unknown):
 first=C(a)
 second=C(b)
 first.run()
 second.run()
 C(unknown).run()
 Plain().run()
"""
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    expect(r, "first.run", "caller", {"a"}, forbidden={"b", "C.run"})
    expect(r, "second.run", "caller", {"b"}, forbidden={"a", "C.run"})
    expect(r, "C(unknown).run", "caller", set(), unknown=True, complete=False, forbidden={"C.run"})
    expect(r, "Plain().run", "caller", {"Plain.run"})


@pytest.mark.parametrize("hook", ["property", "data_descriptor", "dynamic_hook"])
def test_descriptor_or_dynamic_access_stays_open(tmp_path, hook):
    prefix = """def a(): pass
class Descriptor:
 def __get__(self,obj,owner): return a
 def __set__(self,obj,value): pass
"""
    bodies = {
        "property": " @property\n def run(self): return a\n",
        "data_descriptor": " run=Descriptor()\n",
        "dynamic_hook": " def run(self): pass\n def __getattribute__(self,name): return a\n",
    }
    source = (
        prefix
        + "class C:\n def __init__(self): self.run=a\n"
        + bodies[hook]
        + "def caller(): C().run()\n"
    )
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = site(r, "C().run", "caller")
    assert s["names"] == {"a"} and s["complete"]
    assert s["target_provider"] == "jedi-get-signatures"


def test_direct_instance_writes_remain_distinct(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class C:
 def run(self): pass
def caller():
 first=C()
 second=C()
 first.run=a
 second.run=b
 first.run()
 second.run()
"""
        },
        closed=False,
    )
    expect(r, "first.run", "caller", {"C.run"})
    expect(r, "second.run", "caller", {"C.run"})


@pytest.mark.parametrize(
    "source,owner,target,forbidden",
    [
        (
            """def target(): pass
def decorate(cb): return lambda f:f
@decorate(lambda:target())
def f():
 def target(): pass
""",
            "f.<lambda>",
            "target",
            "f.target",
        ),
        (
            """def outer():
 def target(): pass
 def f(cb=lambda:target()):
  def target(): pass
  cb()
 f()
""",
            "outer.f.<lambda>",
            "outer.target",
            "outer.f.target",
        ),
        (
            """def target(): pass
class C:
 def target(self): pass
 def f(self,cb=lambda:target()): cb()
""",
            "C.f.<lambda>",
            "target",
            "C.target",
        ),
    ],
)
def test_header_lambda_resolution_parent(tmp_path, source, owner, target, forbidden):
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = expect(r, "target", owner, {target}, forbidden={forbidden})
    node = next(n for n in r[0] if n["node_id"] == s["execution_owner"])
    assert node["parent"] != node["resolution_parent"]
    assert s["lexical_owner"] == s["execution_owner"]


def test_conditional_namedexpr_and_real_unbound(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def cb(): pass
def conditional(flag):
 flag and (run:=a)
 run()
def unbound():
 cb()
 cb=a
"""
        },
        closed=False,
    )
    expect(r, "run", "conditional", {"a"})
    s = expect(r, "cb", "unbound", {"cb"})
    assert s["target_provider"] == "jedi-get-signatures"


@pytest.mark.parametrize(
    "mutation,targets,unknown",
    [
        ('del table["x"]\n table["x"]=b', set(), True),
        ('if flag: del table["x"]', {"a"}, False),
        ('del table["y"]', set(), True),
        ("del table[key]", set(), True),
    ],
)
def test_slot_deletion_variants(tmp_path, mutation, targets, unknown):
    source = (
        'def a(): pass\ndef b(): pass\ndef caller(flag,key):\n table={"x":a,"y":b}\n '
        + mutation
        + '\n table["x"]()\n'
    )
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    expect(
        r,
        "table['x']",
        "caller",
        targets,
        unknown=unknown,
        complete=not unknown,
        forbidden={"a", "b"} - targets,
    )


@pytest.mark.parametrize(
    "call,unknown",
    [
        ("modify(table)", False),
        ("modify(table=table)", False),
        ("modify(**{'table':table})", False),
        ("modify(*[table])", False),
        ("kw={'table':table}\n modify(**kw)", False),
        ("modify(other={})", False),
        ("modify(*[1],**{'other':2})", False),
    ],
)
def test_container_escape_arguments(tmp_path, call, unknown):
    source = 'def a(): pass\ndef caller(modify):\n table={"x":a}\n ' + call + '\n table["x"]()\n'
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    expect(r, "table['x']", "caller", {"a"}, unknown=unknown, complete=not unknown)


@pytest.mark.parametrize(
    "index,targets",
    [
        ("0", {"a"}),
        ("+0", {"a"}),
        ("1", {"b"}),
        ("-1", {"b"}),
        ("-2", {"a"}),
        ("2", {"a", "b"}),
        ("-3", {"a", "b"}),
        ("key", {"a", "b"}),
    ],
)
def test_sequence_index_boundaries(tmp_path, index, targets):
    source = f"def a(): pass\ndef b(): pass\ndef caller(key):\n table=[a,b]\n table[{index}]()\n"
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = expect(r, f"table[{index}]", "caller", targets, forbidden={"a", "b"} - targets)
    assert s["target_provider"] == "jedi-get-signatures"


def test_contextlib_alias_and_complex_generator(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """from contextlib import contextmanager as cm
class R:
 def work(self): pass
@cm
def simple(): yield R()
@cm
def complex(flag):
 if flag: yield R()
 else: yield R()
def caller(flag):
 with simple() as first: first.work()
 with complex(flag) as second: second.work()
"""
        },
        closed=False,
    )
    first = expect(r, "first.work", "caller", {"R.work"})
    assert first["phase"] == "body"
    assert first["target_provider"] == "jedi-get-signatures"
    expect(r, "second.work", "caller", {"R.work"})


def test_contextmanager_name_shadow_is_not_protocol_proof(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def contextmanager(fn): return fn
class R:
 def work(self): pass
@contextmanager
def acquire(): yield R()
def caller():
 with acquire() as resource: resource.work()
"""
        },
        closed=False,
    )
    s = site(r, "resource.work", "caller")
    assert s["unknown_origin"] and not s["complete"]
    assert "jedi-no-result" in s["unresolved_reasons"]


def test_separate_registries_open_inputs_remain_partial(tmp_path):
    from pathlib import Path

    source = (Path(__file__).parent / "fixtures/python_pipeline/instance_registries.py").read_text()
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    expect(
        r,
        "self.handlers['go']",
        "Registry.dispatch",
        set(),
        forbidden={"b"},
        unknown=True,
        complete=False,
    )


def test_equal_branch_alias_uses_jedi_without_secondary_adjudication(tmp_path):
    source = "def a(): pass\ndef caller(flag):\n if flag: alias=a\n else: alias=a\n alias()\n"
    graph = analyze(tmp_path, {"demo.py": source}, closed=False)
    observed = expect(graph, "alias", "caller", {"a"})
    assert observed["target_provider"] == "jedi-get-signatures"
    assert "resolution_decision" not in observed


def test_conditional_instance_field_keeps_method_alternative(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
class C:
 def __init__(self,flag):
  if flag: self.run=a
 def run(self): pass
def caller(flag): C(flag).run()
"""
        },
        closed=False,
    )
    expect(r, "C(flag).run", "caller", {"a"})


def test_custom_setattr_is_not_a_plain_field_proof(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
class C:
 def __setattr__(self,name,value): pass
 def __init__(self): self.run=a
 def run(self): pass
def caller(): C().run()
"""
        },
        closed=False,
    )
    s = site(r, "C().run", "caller")
    assert s["names"] == {"a"} and s["complete"]
    assert s["target_provider"] == "jedi-get-signatures"


def test_reused_factory_creation_is_not_a_unique_container(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """class Registry:
 def __init__(self): self.handlers={}
 def register(self,key,cb): self.handlers[key]=cb
 def dispatch(self): self.handlers["go"]()
def a(): pass
def b(): pass
def factory(): return Registry()
first=factory()
second=factory()
first.register("go",a)
second.register("go",b)
first.dispatch()
"""
        },
        closed=False,
    )
    s = expect(
        r,
        "self.handlers['go']",
        "Registry.dispatch",
        set(),
        unknown=True,
        complete=False,
        forbidden={"a", "b"},
    )
    assert "jedi-no-result" in s["unresolved_reasons"]


def test_nondata_descriptor_yields_to_instance_field(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class Descriptor:
 def __get__(self,obj,owner): return b
class C:
 run=Descriptor()
 def __init__(self): self.run=a
def caller(): C().run()
"""
        },
        closed=False,
    )
    expect(r, "C().run", "caller", {"a"}, forbidden={"b"})


def test_verified_asynccontextmanager_protocol(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """from contextlib import asynccontextmanager as cm
class R:
 def work(self): pass
@cm
async def acquire(): yield R()
async def caller():
 async with acquire() as resource: resource.work()
"""
        },
        closed=False,
    )
    s = expect(r, "resource.work", "caller", {"R.work"})
    assert s["phase"] == "body"
    assert s["target_provider"] == "jedi-get-signatures"


def test_instance_keyword_escape_retains_field_uncertainty(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
class C:
 def __init__(self): self.run=a
 def run(self): pass
def caller(modify):
 obj=C()
 modify(obj=obj)
 obj.run()
"""
        },
        closed=False,
    )
    expect(r, "obj.run", "caller", {"a"}, forbidden={"C.run"})
