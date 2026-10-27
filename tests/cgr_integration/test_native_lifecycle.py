"""Windows native stop ownership guard: console hosts are not independent JVMs."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cgr_adapter import native


def setup_process(tmp_path, monkeypatch, unexpected=False):
    home = tmp_path / "owned"
    home.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (home / ".lct-code-graph-owned.json").write_text(
        json.dumps(dict(home=str(home.resolve()), state=str(state.resolve()))), encoding="utf-8"
    )
    (state / "native-pid.json").write_text(
        json.dumps(dict(pid=123, created=12, exe="owned-java.exe")), encoding="utf-8"
    )
    console = SimpleNamespace(
        exe=lambda: str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/conhost.exe"),
        terminate=Mock(),
    )
    java = SimpleNamespace(
        exe=lambda: str(home / "java.exe"),
        cmdline=lambda: [str(home), "CommunityEntryPoint"],
        terminate=Mock(),
    )
    alien = SimpleNamespace(
        exe=lambda: str(home / "unrelated.exe"), cmdline=lambda: [], terminate=Mock()
    )
    parent = SimpleNamespace(
        create_time=lambda: 12,
        exe=lambda: "owned-java.exe",
        cmdline=lambda: [str(home), "Neo4jBoot"],
        children=lambda recursive: [console, java] + ([alien] if unexpected else []),
        terminate=Mock(),
    )
    monkeypatch.setattr(native.psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(native.psutil, "Process", lambda pid: parent)
    waited = []
    monkeypatch.setattr(
        native.psutil,
        "wait_procs",
        lambda processes, timeout: (waited.extend(processes) or processes, []),
    )
    return home, state, parent, java, console, alien, waited


def test_stop_owned_java_with_windows_console_hosts(tmp_path, monkeypatch):
    home, state, parent, java, console, _, waited = setup_process(tmp_path, monkeypatch)
    assert native.stop(home, state) == dict(status="stopped")
    parent.terminate.assert_called_once()
    java.terminate.assert_called_once()
    console.terminate.assert_not_called()
    assert waited == [java, parent]


def test_stop_refuses_unexpected_child_before_terminating_anything(tmp_path, monkeypatch):
    home, state, parent, java, console, alien, _ = setup_process(tmp_path, monkeypatch, True)
    with pytest.raises(ValueError, match="Unexpected"):
        native.stop(home, state)
    for process in [parent, java, console, alien]:
        process.terminate.assert_not_called()
