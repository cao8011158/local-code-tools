"""Execution event identity must not depend on unrelated shared AST markers."""

import pytest

from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer


TARGET = "def run(a, b):\n    value = a + b\n    value.call()\n    return value\n"
NOISE = "def other(x):\n    tmp = x + 1\n    return tmp\n"


def events(tmp_path, sources):
    files = [dict(repository="fixture", path=path, text=source, is_test=False)
             for path, source in sources]
    nodes, trees = extract(files)
    graph = Graph(nodes, trees, [dict(name="fixture", path=str(tmp_path))])
    analyzer = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    try:
        scope = next(n["node_id"] for n in nodes if n["qualname"] == "run")
        statements = analyzer.effects.by_scope[scope]
        result = [(e.ident, e.kind, e.node.lineno, e.node.col_offset,
                   e.phase, e.ordered, e.conditional, e.reachable) for e in statements]
        # The previous assignment remains visible before the actual call.
        call = next(e.node for e in statements if e.kind == "call")
        before = analyzer.effects.before(scope, call)
        assert any(e.kind == "write" and e.node.lineno == 2 for e in before)
        assert all(e.node is not call for e in before)
        return result
    finally:
        analyzer.close()


@pytest.mark.parametrize("position", ["before", "after"])
def test_scope_event_ids_ignore_unrelated_context_and_operator_owners(tmp_path, position):
    baseline = events(tmp_path, [("src/a.py", TARGET)])
    files = [("src/a.py", TARGET), ("src/z.py", NOISE)]
    if position == "before":
        files.reverse()
    assert events(tmp_path, files) == baseline
