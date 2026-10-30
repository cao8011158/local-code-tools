"""Actual-source no-change reuse and failed-candidate isolation controls."""

import shutil
from pathlib import Path

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current
from tests.synthetic_support import initialize


def test_actual_sources_no_change_and_failed_candidate(tmp_path, monkeypatch):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    fixture = Path(__file__).with_name("fixtures") / "actual-source-subset/src"
    shutil.copytree(fixture, repo / "src", dirs_exist_ok=True)
    first = build(config, offline=True, lexical_only=True)
    with monkeypatch.context() as patch:
        def unexpected_parse(*args, **kwargs):
            raise AssertionError("Unchanged source was parsed again")
        patch.setattr(extraction, "python_nodes", unexpected_parse)
        reused = build(config, offline=True, lexical_only=True)
    assert reused["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert reused["incremental"]["analysis_scope"]["python_files_parsed"] == 0
    before = current(config)
    path = repo / "src/trpg_state_machine/availability.py"
    path.write_bytes(path.read_bytes().replace(b"context=context", b"context=None"))
    with pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == before
    updated = build(config, offline=True, lexical_only=True)
    assert current(config) == updated["version"]
    assert updated["version"] != first["version"]
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
