"""Original reviewed-entry assertions, independently runnable against 36b0ede."""

import pytest

from tests.test_python_pipeline import analyze
from tests.test_python_review_round3 import check

HEADER = """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
"""


@pytest.mark.parametrize("case", ["closure", "nested_argument"])
def test_review_counterexamples(tmp_path, case):
    if case == "closure":
        text = (
            HEADER
            + """def caller():
 obj=C()
 def mutate(): obj.run=b
 mutate()
 obj.run()
"""
        )
    else:
        text = (
            HEADER
            + """def caller(consume):
 obj=C()
 consume([obj])
 obj.run()
"""
        )
    s = check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"}, True)
    assert s["unresolved_reasons"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]


def test_uncalled_closure_is_not_executed(tmp_path):
    text = (
        HEADER
        + """def caller():
 obj=C()
 def mutate(): obj.run=b
 obj.run()
"""
    )
    check(analyze(tmp_path, {"demo.py": text}, closed=False), "obj.run", {"a"}, {"b"})
