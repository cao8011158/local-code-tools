"""Independent relative-import closure, full-record oracle and boundary checks."""
import shutil
from pathlib import Path

import pytest

from lct.common import ToolError, inventory
from lct.extract import extract
from lct.graph import Graph
from lct.simple_python import certify, component_policy
from lct.storage import FileDependencies, build, current, manifest
from tests.synthetic_support import initialize
from test_common_certificate_independent import records


def setup(tmp_path, noise=0):
    config, repo = initialize(tmp_path / "relative")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    sources = {
        "pkg/base.py": "def first(): return 'first'\ndef second(): return 'second'\n",
        "pkg/alternate.py": "def first(): return 'alternate'\n",
        "pkg/mid.py": "from .base import first as chosen\ndef choose(): return chosen()\n",
        "pkg/sub/entry.py": "from ..mid import choose\ndef run(): return choose()\n",
        "unrelated/base.py": "def first(): return 'unrelated'\ndef run(): return first()\n",
    }
    sources.update({f"noise_{i}.py": f"def idle_{i}(): return {i}\n" for i in range(noise)})
    for path, source in sources.items():
        target = repo / "src" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    return config, repo


@pytest.mark.parametrize("noise", [0, 20])
@pytest.mark.parametrize("change", ["provider", "new-import"])
def test_relative_component_updates_and_keeps_unrelated_files(tmp_path, monkeypatch, noise, change):
    import lct.extract as extraction
    config, repo = setup(tmp_path, noise)
    initial = build(config, offline=True, lexical_only=True)
    assert initial["simple_python_certificate"] == "simple-python-v6"
    old = records(config, initial["version"])
    target = repo / "src/pkg" / ("base.py" if change == "provider" else "mid.py")
    target.write_text(target.read_text().replace("'first'", "'updated'") if change == "provider"
                      else target.read_text().replace("from .base", "from .alternate"))
    original, parsed = extraction.python_nodes, []
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    with pytest.raises(ToolError, match="Injected"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == initial["version"]
    assert records(config, initial["version"]) == old
    parsed.clear()
    updated = build(config, offline=True, lexical_only=True)
    expected = {"src/pkg/base.py", "src/pkg/mid.py", "src/pkg/sub/entry.py"}
    if change == "new-import":
        expected.add("src/pkg/alternate.py")
    assert set(parsed) == expected and len(parsed) == len(expected)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "certified-simple-python-component"
    assert scope["reused_python_files"] == noise + (2 if change == "provider" else 1)
    fresh_config = dict(config, data=str(tmp_path / "fresh-full"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(fresh_config, fresh["version"])
    assert records(config, initial["version"]) == old
    parsed.clear()
    build(config, offline=True, lexical_only=True)
    assert parsed == []


def test_real_errors_provider_with_synthetic_relative_consumer(tmp_path):
    config, repo = setup(tmp_path)
    target = repo / "src/pkg/errors.py"
    fixture = Path(__file__).with_name("fixtures") / "actual-source-subset/src/trpg_state_machine/errors.py"
    shutil.copyfile(fixture, target)
    (repo / "src/pkg/client.py").write_text(
        "from .errors import StateMachineError\n"
        "def make(message): return StateMachineError('code', message)\n")
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["simple_python_certificate"] == "simple-python-v6"
    target.write_text(target.read_text().replace('path: str = ""', 'path: str = "root"'))
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["python_files_parsed"] == 2
    fresh_config = dict(config, data=str(tmp_path / "fresh-full"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(fresh_config, fresh["version"])


@pytest.mark.parametrize("statement", [
    "from ...base import first", "from .missing import first",
    "from .base import missing", "from .base import *", "from . import first",
])
def test_relative_boundaries_do_not_certify(statement, tmp_path):
    config, repo = setup(tmp_path)
    (repo / "src/pkg/mid.py").write_text(statement + "\ndef choose(): pass\n")
    files, repos, _ = inventory(config)
    nodes, asts = extract(files)
    graph = Graph(nodes, asts, repos)
    assert certify(files, asts, graph=graph) is None
    assert component_policy(files, asts, graph) is None


def test_relative_dataclass_name_does_not_use_external_helper_exception(tmp_path):
    config, repo = setup(tmp_path)
    (repo / "src/pkg/dataclasses.py").write_text("def dataclass(): pass\n")
    (repo / "src/pkg/fake.py").write_text(
        "from .dataclasses import dataclass\n"
        "@dataclass(frozen=True, slots=True)\nclass Fake:\n    code: str\n")
    files, repos, _ = inventory(config)
    nodes, asts = extract(files)
    graph = Graph(nodes, asts, repos)
    assert certify(files, asts, graph=graph) is None


def test_relative_import_reverse_lookup_uses_normalized_index(tmp_path):
    measurements = []
    for noise in (0, 20):
        config, repo = setup(tmp_path / str(noise))
        for i in range(noise):
            package = repo / f"src/extra_{i}"
            package.mkdir()
            (package / "base.py").write_text("def first(): pass\n")
            (package / "caller.py").write_text("from .base import first\ndef call(): first()\n")
        built = build(config, offline=True, lexical_only=True)
        assert built["simple_python_certificate"] == "simple-python-v6"
        folder, metadata = manifest(config, built["version"])
        dependencies = FileDependencies(folder, metadata)
        try:
            query = ("select source_repository,source_path from import_lookup_keys "
                     "where lookup_repository=? and module=?")
            params = (config["repositories"][0]["name"], "pkg.base")
            plan = list(dependencies.db.execute("explain query plan " + query, params))
            assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plan), plan
            assert not any("SCAN" in row[3] for row in plan), plan
            expected = {(params[0], "src/pkg/mid.py")}
            probes = []
            for _ in range(3):
                traces, steps = [], [0]
                def progress():
                    steps[0] += 1
                    return 0
                dependencies.db.set_trace_callback(traces.append)
                dependencies.db.set_progress_handler(progress, 1)
                try:
                    result = dependencies.importers(*params)
                finally:
                    dependencies.db.set_trace_callback(None)
                    dependencies.db.set_progress_handler(None, 0)
                assert result == expected and len(traces) == 1
                assert "'pkg.base'" in traces[0]
                probes.append(steps[0])
            # First and repeated executions can have different SQLite VM setup.
            # Compare each path separately across unrelated-data growth below.
            assert all(steps > 0 for steps in probes)
            assert probes[1] == probes[2]
            measurements.append(probes)
        finally:
            dependencies.close()
    assert measurements[0] == measurements[1]
