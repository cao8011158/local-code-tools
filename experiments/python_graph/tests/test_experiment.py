"""Harness validation, not acceptance assertions that every analyzer is correct."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from run import synthetic  # noqa: E402
from syntax import inventory, normalize  # noqa: E402


def test_frozen_independent_truth_and_sources():
    """Changing or removing a difficult fixture must invalidate the frozen contract."""
    frozen = json.loads((HERE / "truth-freeze.json").read_text())
    for path, value in frozen["sha256"].items():
        assert hashlib.sha256((HERE / path).read_bytes()).hexdigest() == value
    assert frozen["candidate_runs_so_far"] == 0
    assert len(json.loads((HERE / "truth.json").read_text())["sites"]) == 39


def test_definition_body_and_reference_locations():
    """Definitions execute defaults outside the body; passing references creates no call."""
    plan = synthetic()
    sites = {s["id"]: s for s in plan["sites"]}
    assert sites["default"]["context"] == "sample:<module>"
    source = next(s for s in plan["sources"] if s["module"] == "sample")
    calls, definitions = inventory(source)
    default = next(c for c in calls if c["line"] == sites["default"]["line"])
    assert default["phase"] == "definition"
    assert default["context"] == "sample:<module>"
    lam = next(c for c in calls if c["line"] == sites["lambda_body"]["line"])
    assert lam["context"] == "sample:lambda_factory.<lambda>"
    for key in ("assignment", "container", "factory_return"):
        assert all(c["line"] != sites[key]["line"] for c in calls)
    assert any(n["id"] == "sample:lambda_factory.<lambda>" for n in definitions)


def test_all_regressions_and_unknown_origins_are_preserved():
    """A single known candidate in mixed has an explicitly incomplete oracle set."""
    sites = {s["id"]: s for s in synthetic()["sites"]}
    assert {"string", "callback_mixed", "bare", "default", "staticmethod_callback"} <= sites.keys()
    assert sites["callback_mixed"]["targets"] == ["sample:target"]
    assert sites["callback_mixed"]["complete"] is False
    assert sites["string"]["targets"] == []
    assert sites["bare"]["targets"] == []


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    """Run actual candidates with network-denied workers in new synthetic repositories."""
    out = tmp_path_factory.mktemp("evaluation") / "run"
    proc = subprocess.run(
        [sys.executable, "-B", str(HERE / "run.py"), "--output", str(out), "--timeout", "90"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=150,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out, json.loads((out / "summary.json").read_text())


def test_candidates_really_ran_without_network(observed):
    """Process success is evidence of execution, not a passing relation score."""
    out, summary = observed
    assert set(summary["runs"]) == {"synthetic", "cross-matched", "cross-mismatched"}
    for name, run in summary["runs"].items():
        for tool, result in run["tools"].items():
            assert result["status"] == "completed", (name, tool, result)
            raw = json.loads((out / name / (tool + ".json")).read_text())
            assert raw["network_denied"] and raw["network_attempts_blocked"] == 0


def test_repairs_and_tool_semantics_stay_separate(observed):
    """Do not silently turn Pyan USES or Jedi candidates into certain CALLS."""
    _, summary = observed
    tools = summary["runs"]["synthetic"]["tools"]
    current = tools["current"]
    assert current["bounded_target_metric"]["fp"] == 0
    assert current["bounded_target_metric"]["fn"] == 0
    assert not current["false_certainty_sites"]
    for tool in ("jedi", "pyan3"):
        assert not tools[tool]["false_certainty_sites"]
        assert all(r["asserted_certain"] is False for r in tools[tool]["records"])
    assert tools["pyan3"]["bounded_target_metric"] is None
    assert {r["adapted_relation"] for r in tools["pyan3"]["records"]} == {"USES_CONTEXT_ONLY"}


def test_cross_revision_negative_control_is_not_dropped(observed):
    """The current Graph keeps mismatched local RE definitions at a boundary."""
    _, summary = observed
    matched = summary["runs"]["cross-matched"]["tools"]["current"]["records"][0]
    mismatch = summary["runs"]["cross-mismatched"]["tools"]["current"]["records"][0]
    assert matched["actual_targets_or_context_uses"] == ["dnd5e_engine.evaluation:evaluate"]
    assert mismatch["actual_targets_or_context_uses"] == []
    assert any(r["status"] == "boundary" for r in mismatch["raw"])


def test_module_identity_does_not_lose_to_long_init_suffix():
    """An init module's spelling must not steal names from a more specific module."""
    modules = ["trpg_state_machine.__init__", "trpg_state_machine.errors"]
    assert (
        normalize("trpg_state_machine.errors.Issue", modules) == "trpg_state_machine.errors:Issue"
    )
    assert (
        normalize("trpg_state_machine.errors.StateMachineError.__init__", modules)
        == "trpg_state_machine.errors:StateMachineError.__init__"
    )
