"""Fourth review: applicability of method summaries and copied-slot uncertainty."""

import pytest

from tests.test_python_pipeline import analyze
from tests.test_python_review_round3 import check

CASES = [
    (
        "coroutine_creation",
        """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 async def change(self): self.run=b
def caller():
 obj=C()
 obj.change()
 obj.run()
""",
        "obj.run",
        {"a"},
        {"b"},
        False,
    ),
    (
        "unreachable_store",
        """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 def change(self):
  return
  self.run=b
def caller():
 obj=C()
 obj.change()
 obj.run()
""",
        "obj.run",
        {"a"},
        {"b"},
        False,
    ),
    (
        "callsite_method_shadow",
        """def a(): pass
def b(): pass
def noop(): pass
class C:
 def __init__(self): self.run=a
 def change(self): self.run=b
def caller():
 obj=C()
 obj.change=noop
 obj.change()
 obj.run()
""",
        "obj.run",
        {"a"},
        {"b"},
        False,
    ),
    (
        "conditional_source_copy",
        """def a(): pass
def b(): pass
def caller(flag):
 original={"go":a}
 if flag:
  original["go"]=b
 copied={**original}
 copied["go"]()
""",
        "copied['go']",
        {"a", "b"},
        {"caller"},
        True,
    ),
    (
        "escaped_source_copy",
        """def a(): pass
def caller(mutate):
 original={"go":a}
 mutate(original)
 copied={**original}
 copied["go"]()
""",
        "copied['go']",
        {"a"},
        {"caller"},
        True,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_review_counterexample(tmp_path, case):
    label, source, expression, _, _, _ = case
    expected = {
        "coroutine_creation": {"a", "b"},
        "unreachable_store": {"a", "b"},
        "callsite_method_shadow": {"a", "b"},
        "conditional_source_copy": set(),
        "escaped_source_copy": set(),
    }[label]
    result = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = check(result, expression, expected, unknown=not expected)
    assert s["line"] == len(source.splitlines())
    if case[0] == "callsite_method_shadow":
        check(result, "obj.change", {"C.change"})


@pytest.mark.parametrize(
    "modifier,body,targets,phase",
    [
        ("", "self.run=b", {"a", "b"}, "ordinary-call"),
        ("async ", "self.run=b", {"a", "b"}, "coroutine-create"),
        ("", "self.run=b\n  yield 1", {"a", "b"}, "generator-create"),
        ("async ", "self.run=b\n  yield 1", {"a", "b"}, "async-generator-create"),
        ("", "return\n  self.run=b", {"a", "b"}, "ordinary-call"),
        ("", "self.run=b\n  return\n  self.run=a", {"a", "b"}, "ordinary-call"),
    ],
)
def test_method_execution_phase_controls(tmp_path, modifier, body, targets, phase):
    source = f"""def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 {modifier}def change(self):
  {body}
def caller():
 obj=C()
 obj.change()
 obj.run()
"""
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = check(r, "obj.run", targets, {"a", "b"} - targets)
    invocation = check(r, "obj.change", {"C.change"})
    assert s["target_provider"] == invocation["target_provider"] == "jedi-get-signatures"
    assert s["phase"] == invocation["phase"] == "body"


@pytest.mark.parametrize(
    "statements,targets",
    [
        ("obj.change=noop\n obj.change()", {"a", "b"}),
        ("obj.change()\n obj.change=noop", {"a", "b"}),
        ("callback=obj.change\n obj.change=noop\n callback()", {"a", "b"}),
    ],
)
def test_override_order_and_saved_bound_target(tmp_path, statements, targets):
    source = f"""def a(): pass
def b(): pass
def noop(): pass
class C:
 def __init__(self): self.run=a
 def change(self): self.run=b
def caller():
 obj=C()
 {statements}
 obj.run()
"""
    check(
        analyze(tmp_path, {"demo.py": source}, closed=False),
        "obj.run",
        targets,
        {"a", "b"} - targets,
    )


def test_bound_alias_uses_body_receiver_not_surface_object(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 def change(self): self.run=b
def caller():
 first=C()
 second=C()
 first.change=second.change
 first.change()
 first.run()
 second.run()
"""
        },
        closed=False,
    )
    check(r, "first.run", {"a", "b"})
    check(r, "second.run", {"a", "b"})


def test_constructor_return_stops_unreachable_effects(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class C:
 def __init__(self):
  self.run=a
  return
  self.change()
  self.run=b
 def change(self): self.run=b
def caller(): C().run()
"""
        },
        closed=False,
    )
    check(r, "C().run", {"a", "b"})


@pytest.mark.parametrize("resume", ["await obj.change()", "pending=obj.change()\n await pending"])
def test_await_resumption_is_explicitly_unknown(tmp_path, resume):
    source = f"""def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 async def change(self): self.run=b
async def caller():
 obj=C()
 {resume}
 obj.run()
"""
    s = check(analyze(tmp_path, {"demo.py": source}, closed=False), "obj.run", {"a", "b"})
    assert s["target_provider"] == "jedi-get-signatures"


COPY_CASES = [
        ('original={"go":a}\n if flag: original["go"]=b', "{**original}", "", {"a", "b"}, True),
        ('original={"go":a}\n if flag: original["go"]=b', '{**original,"go":c}', "", {"c"}, False),
        (
            'original={"go":a}\n if flag: del original["go"]',
            '{"go":b,**original}',
            "",
            {"a", "b"},
            True,
        ),
        ('original={}\n if flag: original["go"]=b', '{"go":a,**original}', "", {"a", "b"}, True),
        (
            'original={"go":a,"other":b}\n if flag: original["other"]=c',
            "{**original}",
            "",
            {"a"},
            False,
        ),
        ('original={"go":a}\n mutate(original)', "{**original}", "", {"a"}, True),
        ('original={"go":a}\n mutate(original)', '{**original,"go":b}', "", {"b"}, False),
        ('original={"go":a}\n mutate(original)', '{"go":b,**original}', "", {"a", "b"}, True),
        ('original={"go":a}', "{**original}", 'original["go"]=b', {"a"}, False),
        ('original={"go":a}', "{**original}", "", {"a"}, False),
    ]


@pytest.mark.parametrize("setup,expression,after,targets,uncertain", COPY_CASES)
def test_copy_uncertainty_and_key_override(tmp_path, setup, expression, after, targets, uncertain):
    source = f"""def a(): pass
def b(): pass
def c(): pass
def caller(flag,mutate):
 {setup}
 copied={expression}
 {after}
 copied["go"]()
"""
    expected = (set(), {"c"}, {"b"}, {"a"}, set(), set(),
                {"b"}, {"b"}, set(), set())[
                    COPY_CASES.index((setup, expression, after, targets, uncertain))]
    check(analyze(tmp_path, {"demo.py": source}, closed=False),
          "copied['go']", expected, unknown=not expected)


def test_generator_resumption_is_not_simulated(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 def change(self):
  self.run=b
  yield 1
def caller():
 obj=C()
 pending=obj.change()
 next(pending)
 obj.run()
"""
        },
        closed=False,
    )
    s = check(r, "obj.run", {"a", "b"})
    assert s["target_provider"] == "jedi-get-signatures"


def test_deferred_initializer_has_no_body_effect_proof(tmp_path):
    from tests.test_python_pipeline import site

    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
class C:
 async def __init__(self): self.run=a
def caller(): C().run()
"""
        },
        closed=False,
    )
    s = site(r, "C().run", "caller")
    assert s["names"] == {"a"} and s["complete"]
    assert s["target_provider"] == "jedi-get-signatures"
