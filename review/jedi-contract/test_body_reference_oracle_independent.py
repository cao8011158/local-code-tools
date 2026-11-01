"""Source-backed extra references must respect actual Python binding and phase."""
import ast
import copy
import json

import pytest

from lct.common import canonical, digest
from tests.limited_precision_comparison import assert_limited_refinement


def fixture(case):
    sources = {
        "valid": "class Kind: pass\ndef use():\n    Kind\n",
        "parameter-shadow": "class Kind: pass\ndef use(Kind):\n    Kind\n",
        "later-local-shadow": "class Kind: pass\ndef use():\n    Kind\n    Kind=1\n",
        "module-rebound": "class Kind: pass\ndef use():\n    Kind\nKind=1\n",
        "nested-owner": "class Kind: pass\ndef use():\n    def inner():\n        Kind\n",
        "annotation-only": "class Kind: pass\ndef use():\n    value: Kind\n",
        "fake-location": "class Kind: pass\ndef use():\n    Kind\n",
    }
    content = sources[case]
    repo, path = "sample", "src/sample.py"
    module = "sample:src/sample.py:module:sample#1"
    target = "sample:src/sample.py:class:Kind#1"
    owner = "sample:src/sample.py:function:use#1"
    use = next(n for n in ast.parse(content).body if isinstance(n, ast.FunctionDef))
    token = next(n for n in ast.walk(use) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load) and n.id == "Kind")
    rows = []
    for identifier, name, kind, line, end, parent in (
        (module, "sample", "module", 1, len(content.splitlines()), ""),
        (target, "Kind", "class", 1, 1, module),
        (owner, "use", "function", 2, use.end_lineno, module),
    ):
        data = dict(node_id=identifier, name=name, qualname=name, kind=kind,
                    repository=repo, path=path, definition_line=line, start=line, end=end,
                    version_id="v-" + name, parent=parent, snapshot_id="capture")
        rows.append((identifier, repo, path, kind, canonical(data), "fingerprint"))
    fact = dict(source=owner, target=target, kind="REFERENCES", status="resolved",
                source_version_id="v-use", target_version_id="v-Kind",
                basis="AST value reference; never implies invocation", phase="body",
                expression="Kind", line=token.lineno, column=token.col_offset)
    if case == "fake-location":
        fact["line"] = 1
    fact["edge_id"] = digest(canonical(fact))
    edge = (fact["edge_id"], owner, target, "REFERENCES", "resolved", canonical(fact))
    fresh = dict(nodes=sorted(rows), edges=[])
    actual = copy.deepcopy(fresh)
    actual["edges"] = [edge]
    return actual, fresh, {(repo, path): content}


def test_source_true_body_reference_is_valid_additional_precision():
    assert_limited_refinement(*fixture("valid"))


@pytest.mark.parametrize("case", ["parameter-shadow", "later-local-shadow", "module-rebound",
                                  "nested-owner", "annotation-only", "fake-location"])
def test_unproved_body_reference_gain_is_rejected(case):
    with pytest.raises(AssertionError):
        assert_limited_refinement(*fixture(case))
