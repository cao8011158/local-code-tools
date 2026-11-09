"""Full-oracle admission on the exact three-file captured business subset."""
import ast
import shutil
from pathlib import Path

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer
from lct.storage import build
from tests.synthetic_support import initialize
from tests.test_actual_item_unit_incremental import records
from tests.test_batch3_actual_acceptance import semantic
from tests.semantic_comparison import assert_semantic_equal

SOURCE = (Path(__file__).parents[1] / "review/batch4-incremental/fixtures"
          / "actual-source-subset/src/trpg_state_machine")


def setup(tmp_path, noise=0):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    for source in SOURCE.glob("*.py"):
        shutil.copyfile(source, target / source.name)
    for i in range(noise):
        (repo / f"src/unrelated_{i}.py").write_text(f"def unrelated_{i}():\n    return {i}\n")
    return config, repo, target


def oracle(tmp_path, config, updated):
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, updated["version"]),
                          semantic(fresh_config, fresh["version"]))


@pytest.mark.parametrize("noise", [0, 20])
def test_actual_three_file_availability_local_and_full_oracle(tmp_path, noise):
    config, repo, target = setup(tmp_path, noise)
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["graph"]["jedi_queries_executed"] > 0
    old = records(config, baseline["version"])
    module = target / "availability.py"
    module.write_bytes(module.read_bytes().replace(b"context=context", b"context=None"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)
    assert records(config, baseline["version"]) == old


def test_connected_caller_is_selected_and_matches_full(tmp_path):
    config, repo, target = setup(tmp_path)
    (repo / "src/caller.py").write_text(
        "from trpg_state_machine.availability import AvailabilityRuntime\n"
        "def use(value):\n    return AvailabilityRuntime().query_action_availability("
        "value, value, value, value, context=value)\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["graph"]["jedi_queries_executed"] > 0
    module = target / "availability.py"
    module.write_bytes(module.read_bytes().replace(b"context=context", b"context=None"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)


def test_errors_passive_default_and_property_with_importer(tmp_path):
    config, repo, target = setup(tmp_path)
    (repo / "src/consumer.py").write_text(
        "from trpg_state_machine.errors import Issue, StateMachineError\n"
        "def use(message):\n    issue = Issue('x', '', message)\n"
        "    return StateMachineError(issue.code, message).code\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["graph"]["jedi_queries_executed"] > 0
    module = target / "errors.py"
    module.write_bytes(module.read_bytes().replace(b'path: str = ""', b'path: str = "root"'))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["reason"] == "incremental-owners"
    oracle(tmp_path, config, updated)


@pytest.mark.parametrize("filename,old,new", [
    ("errors.py", "code: str", "code: dangerous()"),
    ("errors.py", "code: str", "code: External"),
    ("errors.py", "@dataclass(frozen=True, slots=True)",
     "@dataclass(frozen=True, slots=True, init=False)"),
    ("errors.py", "class StateMachineError(Exception):", "class StateMachineError(CustomBase):"),
    ("errors.py", "@property", "@other_property"),
    ("errors.py", "return self.issue.code", "return self.issue.code()"),
    ("errors.py", "super().__init__(message)", "super().other(message)"),
    ("errors.py", "path: str = \"\"", "path: str = factory()"),
    ("availability.py", "self._combat.query_action_availability",
     "getattr(self, '_combat').query_action_availability"),
])
def test_unsafe_form_does_not_gain_certificate(tmp_path, filename, old, new):
    config, _, target = setup(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    assert first["graph"]["jedi_queries_executed"] > 0
    module = target / filename
    assert old in module.read_text()
    module.write_text(module.read_text().replace(old, new))
    result = build(config, offline=True, lexical_only=True)
    assert result["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    oracle(tmp_path, config, result)
