"""Closed relative imports must select their captured provider and match full analysis."""
import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.simple_python import CERTIFICATE
from lct.python_incremental import prepare
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize
from tests.semantic_comparison import assert_semantic_equal
from tests.test_batch3_actual_acceptance import semantic


def records(config, version):
    folder, _ = manifest(config, version)
    result = {}
    for file, tables in (("catalog.sqlite", ("nodes", "edges")),
                         ("graph-sites.sqlite", ("sites", "query_observations",
                                                 "import_requests", "import_dependencies",
                                                 "value_nodes", "value_edges", "value_reads"))):
        with sqlite3.connect(folder / file) as db:
            for table in tables:
                result[table] = sorted(tuple(row) for row in db.execute(f"select * from {table}")) if table in {
                    "value_edges", "value_reads"} else sorted(json.dumps(json.loads(raw), sort_keys=True)
                    for (raw,) in db.execute(f"select data from {table}"))
    return result


def fixture(tmp_path, noise=0, caller="from .b import f as alias\ndef run(): alias()\n"):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    package = repo / "src/pkg"
    package.mkdir()
    (package / "a.py").write_text(caller)
    (package / "b.py").write_text("def f(): pass\ndef other(): pass\n")
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"def idle_{i}(): pass\n")
    return config, repo, package


@pytest.mark.parametrize("noise", [0, 20])
def test_relative_provider_change_is_local_and_full_equal(tmp_path, monkeypatch, noise):
    config, repo, package = fixture(tmp_path, noise)
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    before = records(config, first["version"])
    parsed = []
    original = extraction.python_nodes
    def count(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", count)
    (package / "b.py").write_text("def f(): other()\ndef other(): pass\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert parsed == ["src/pkg/b.py"]
    assert updated["incremental"]["analysis_scope"]["owner_analysis_iterations"] >= 1
    assert records(config, first["version"]) == before
    oracle = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(oracle, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, updated["version"]),
                          semantic(oracle, fresh["version"]))


def test_new_relative_provider_and_failed_publication(tmp_path):
    config, repo, package = fixture(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    old = records(config, first["version"])
    (package / "c.py").write_text("def f(): pass\n")
    (package / "a.py").write_text("from .c import f\ndef run(): f()\n")
    from lct.common import ToolError
    with pytest.raises(ToolError, match="Injected interruption"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == first["version"] and records(config, first["version"]) == old
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    oracle = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(oracle, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, updated["version"]),
                          semantic(oracle, fresh["version"]))


def test_parent_level_and_same_named_other_package_stay_separate(tmp_path, monkeypatch):
    config, repo, package = fixture(tmp_path)
    (package / "a.py").unlink()
    nested = package / "sub"
    nested.mkdir()
    (nested / "a.py").write_text("from ..b import f as renamed\ndef run(): renamed()\n")
    other = repo / "src/elsewhere"
    other.mkdir()
    (other / "b.py").write_text("def f(): pass\n")
    (other / "a.py").write_text("from .b import f\ndef use(): f()\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    parsed = []
    original = extraction.python_nodes
    def count(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", count)
    (package / "b.py").write_text("def f(): other()\ndef other(): pass\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert parsed == ["src/pkg/b.py"]
    oracle = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(oracle, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, updated["version"]),
                          semantic(oracle, fresh["version"]))


def test_old_certificate_fails_before_any_local_evidence_read():
    assert prepare(None, {"simple_python_certificate": "simple-python-v5"}, [], [],
                   dependencies=None, graph_sites=None) == (
                       None, "previous-simple-python-certificate-unavailable")


def test_captured_relative_dataclasses_cannot_impersonate_stdlib(tmp_path):
    config, _, package = fixture(tmp_path, caller=(
        "from .dataclasses import dataclass\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class C:\n    value: str\n"))
    (package / "dataclasses.py").write_text("def dataclass(): pass\n")
    result = build(config, offline=True, lexical_only=True)
    assert result["simple_python_certificate"] is None


def test_relative_dictionary_flow_not_certified(tmp_path):
    config, _, package = fixture(tmp_path, caller=(
        "from .b import registry\ndef run(): registry['go']()\n"))
    (package / "b.py").write_text("def f(): pass\nregistry={'go':f}\n")
    result = build(config, offline=True, lexical_only=True)
    assert result["simple_python_certificate"] is None


@pytest.mark.parametrize("caller", [
    "from . import b\ndef run(): b.f()\n",
    "from .b import *\ndef run(): f()\n",
    "from ...b import f\ndef run(): f()\n",
    "from .absent import f\ndef run(): f()\n",
    "from .dataclasses import dataclass\n@dataclass(frozen=True, slots=True)\nclass C:\n    x: str\n",
])
def test_unsupported_relative_forms_fall_back(tmp_path, caller):
    config, _, _ = fixture(tmp_path, caller=caller)
    result = build(config, offline=True, lexical_only=True)
    assert result["simple_python_certificate"] is None
