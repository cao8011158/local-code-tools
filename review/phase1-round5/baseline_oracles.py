"""The initial 18 review oracles, isolated for rerunning against fdc56dd.

Expected failures are real assertions, without xfail or baseline-dependent answers.
"""

import pytest

from tests.test_python_pipeline import analyze, site
from tests.test_python_review_round3 import check


def source(body, operation="obj.change()", asynchronous=False):
    return f"""def a(): pass
def b(): pass
class C:
 def __init__(receiver): receiver.run=a
 {"async " if asynchronous else ""}def change(receiver):
  {body}
async def caller(flag,consume):
 obj=C()
 {operation}
 obj.run()
"""


@pytest.mark.parametrize(
    "binding",
    ["receiver=other", "del receiver", "receiver: object=other", "receiver,other=(other,receiver)"],
)
def test_receiver_binding_invalidates_summary(tmp_path, binding):
    text = source(binding + "\n  receiver.run=b")
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert "receiver-binding-changed" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


AWAIT_FORMS = [
    "await obj.change()",
    "value=await obj.change()",
    "if await obj.change(): pass",
    "consume(await obj.change())",
    "value=(await obj.change(),)",
    "value=flag and await obj.change()",
    "pending=obj.change()\n if await pending: pass",
]


@pytest.mark.parametrize("operation", AWAIT_FORMS)
def test_await_position_matrix(tmp_path, operation):
    text = source("receiver.run=b", operation, asynchronous=True)
    s = check(
        analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", set(), {"a", "b"}, True
    )
    assert "deferred-method-resumption-not-modeled" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("receiver.run=b", {"b"}),
        ("receiver: object\n  receiver.run=b", {"b"}),
        ("return\n  receiver=other\n  receiver.run=b", {"a"}),
        ("receiver.run=b\n  return\n  del receiver", {"b"}),
        ("local=a\n  receiver.run=b", {"b"}),
    ],
)
def test_straight_line_binding_controls(tmp_path, body, expected):
    check(
        analyze(tmp_path, {"demo.py": source(body)}, closed=False),
        "obj.run",
        expected,
        {"a", "b"} - expected,
    )


@pytest.mark.parametrize("constructor", [True, False])
def test_constructor_and_method_share_stability_check(tmp_path, constructor):
    text = source("receiver=other\n  receiver.run=b")
    if constructor:
        text = text.replace(
            "def __init__(receiver): receiver.run=a",
            "def __init__(receiver):\n  receiver=other\n  receiver.run=b",
        ).replace(" obj.change()", " pass")
        s = site(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", "caller")
        assert not s["complete"] and s["unknown_origin"]
        assert "receiver-binding-changed" in s["unresolved_reasons"]
        assert not s["names"]
    else:
        check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
