"""Real complex selected modules with unrelated proven passive files."""
import json
import ast
import shutil
import sqlite3
from pathlib import Path

import pytest

import lct.extract as extraction
from lct.passive_python import certify as passive_certify
from lct.python_incremental import _PASSIVE_NODE_QUERY
from lct.storage import build, manifest
from lct.common import ToolError
from tests.synthetic_support import initialize
from tests.test_batch3_actual_acceptance import semantic as full_semantic
from tests.semantic_comparison import assert_semantic_equal

ROOT = Path(__file__).parents[1] / "review/batch4-incremental/fixtures"
EXECUTION = ROOT / "actual-related-source/src/trpg_state_machine/_execution.py"
ERRORS = ROOT / "actual-source-subset/src/trpg_state_machine/errors.py"


def semantic(config, version):
    folder, _ = manifest(config, version)
    result = {}
    for name, tables in (("catalog.sqlite", ("nodes", "edges")),
                         ("graph-sites.sqlite", ("sites", "query_observations",
                                                 "import_requests", "import_dependencies",
                                                 "analysis_reads", "analysis_watches",
                                                 "analysis_input_scopes", "analysis_input_members",
                                                 "analysis_input_consumers", "value_nodes",
                                                 "value_edges", "value_reads"))):
        with sqlite3.connect(folder / name) as db:
            for table in tables:
                columns = {r[1] for r in db.execute(f"pragma table_info({table})")}
                if "data" in columns:
                    result[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                           for (raw,) in db.execute(f"select data from {table}"))
                else:
                    result[table] = sorted(tuple(r) for r in db.execute(f"select * from {table}"))
    return result


@pytest.mark.parametrize("noise,changed", [(0, "_execution"), (20, "_execution"),
                                            (20, "errors")])
def test_real_execution_and_errors_reuse_only_passive_noise(tmp_path, monkeypatch, noise, changed):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] is None
    old = semantic(config, first["version"])
    source = target / f"{changed}.py"
    assert source.read_bytes() == (EXECUTION if changed == "_execution" else ERRORS).read_bytes()
    before, after = ((b'"actor"', b'"actor_changed"') if changed == "_execution"
                     else (b'path: str = ""', b'path: str = "root"'))
    assert before in source.read_bytes()
    source.write_bytes(source.read_bytes().replace(before, after, 1))
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == (
        "incremental-owners")
    if changed == "_execution":
        assert sorted(parsed) == ["src/trpg_state_machine/_execution.py"]
    else:
        assert sorted(parsed) == ["src/trpg_state_machine/errors.py"]
    scope = updated["incremental"]["analysis_scope"]
    if changed == "_execution":
        assert scope["context_source_files"] == noise + 2
        assert scope["context_source_bytes"] > 0
        assert scope["python_ast_context_files"] == 1
        assert scope["reused_python_files"] == noise + 1
    assert semantic(config, first["version"]) == old
    full_config = dict(config, data=str(tmp_path / "fresh"))
    fresh = build(full_config, offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(full_config, fresh["version"]))


def test_passive_proof_is_strict_v6_subset():
    file = dict(repository="repo", path="src/noise.py", sha256="example")
    for source in ("def plain():\n    return 1\n", "\"\"\"doc\"\"\"\ndef plain(x):\n    pass\n"):
        assert passive_certify(file, ast.parse(source)) is not None
    for source in ("def type():\n    return 1\n", "def plain(type):\n    return 1\n",
                   "def plain():\n    return absent\n", "def plain(x=1):\n    pass\n",
                   "def plain():\n    return factory()\n", "@decorator\ndef plain():\n    pass\n",
                   "def plain():\n    return x.y\n", "value = 1\n",
                   "from x import y\n", "class Plain:\n    pass\n"):
        assert passive_certify(file, ast.parse(source)) is None, source


def test_passive_catalog_lookup_uses_file_scoped_index():
    steps = []
    for unrelated in (0, 20, 100):
        with sqlite3.connect(":memory:") as db:
            db.execute("create table nodes(node_id text primary key,repository text,kind text,path text)")
            db.execute("create index node_scope on nodes(repository,kind,path)")
            db.execute("insert into nodes values('target','repo','module','src/target.py')")
            db.executemany("insert into nodes values(?,?,?,?)", (
                (f"other_{i}", "repo", "module", f"src/other_{i}.py")
                for i in range(unrelated)))
            plan = [r[3] for r in db.execute("explain query plan " + _PASSIVE_NODE_QUERY,
                                            ("repo", "src/target.py"))]
            assert any("SEARCH nodes USING INDEX node_scope" in detail for detail in plan)
            assert not any("SCAN nodes" in detail for detail in plan)
            count = [0]
            def tick():
                count[0] += 1
                return 0
            db.set_progress_handler(tick, 1)
            assert list(db.execute(_PASSIVE_NODE_QUERY, ("repo", "src/target.py"))) == [("target",)]
            db.set_progress_handler(None, 0)
            steps.append(count[0])
    assert steps[0] == steps[1] == steps[2], steps


def test_prior_incoming_passive_provider_does_not_discard_other_proofs(tmp_path, monkeypatch):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    source = target / "_execution.py"
    source.write_bytes(source.read_bytes() + b"\nfrom noise_7 import pure_7\nresult_7 = pure_7()\n")
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    build(config, offline=True, lexical_only=True)
    source.write_bytes(source.read_bytes().replace(b'"actor"', b'"actor_changed"', 1))
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(parsed) == ["src/trpg_state_machine/_execution.py"]
    assert updated["incremental"]["analysis_scope"]["reused_python_files"] == 21
    full_config = dict(config, data=str(tmp_path / "fresh"))
    fresh = build(full_config, offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(full_config, fresh["version"]))


def test_new_import_of_passive_provider_expands_selected_context(tmp_path, monkeypatch):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    build(config, offline=True, lexical_only=True)
    source = target / "_execution.py"
    source.write_bytes(source.read_bytes() + b"\nfrom noise_7 import pure_7\nresult_7 = pure_7()\n")
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(parsed) == ["src/trpg_state_machine/_execution.py"]
    fresh = build(dict(config, data=str(tmp_path / "fresh")), offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(dict(config, data=str(tmp_path / "fresh")), fresh["version"]))


def test_general_failed_publication_preserves_old_view_then_retries(tmp_path):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    first = build(config, offline=True, lexical_only=True)
    old = semantic(config, first["version"])
    source = target / "_execution.py"
    source.write_bytes(source.read_bytes().replace(b'"actor"', b'"actor_changed"', 1))
    with pytest.raises(ToolError):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert semantic(config, first["version"]) == old
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    same = build(config, offline=True, lexical_only=True)
    assert same["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert semantic(config, updated["version"]) == semantic(config, same["version"])


def test_deleted_passive_source_keeps_remaining_unrelated_proofs(tmp_path, monkeypatch):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    build(config, offline=True, lexical_only=True)
    (repo / "src/noise_7.py").unlink()
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(parsed) == ([] if not (repo / "src/noise_7.py").exists() else
                              ["src/trpg_state_machine/_execution.py", "src/trpg_state_machine/errors.py"])
    full_config = dict(config, data=str(tmp_path / "fresh"))
    fresh = build(full_config, offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(full_config, fresh["version"]))


def test_complex_capture_becoming_simple_rebuilds_local_source(tmp_path):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    build(config, offline=True, lexical_only=True)
    (target / "_execution.py").write_text("def execution():\n    return 1\n")
    (target / "errors.py").write_text("def error():\n    return 2\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert updated["simple_python_certificate"] is None
    full_config = dict(config, data=str(tmp_path / "fresh"))
    fresh = build(full_config, offline=True, lexical_only=True)
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(full_config, fresh["version"]))


def test_local_preserves_passive_sources_for_new_complex_capture(tmp_path, monkeypatch):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for i in range(20):
        (repo / f"src/noise_{i}.py").write_text(f"def pure_{i}():\n    return {i}\n")
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] is None
    (repo / "src/noise_0.py").write_text("def pure_0():\n    return 200\n")
    local = build(config, offline=True, lexical_only=True)
    assert local["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert local["passive_python_count"] == 20
    target = repo / "src/trpg_state_machine"
    target.mkdir()
    shutil.copyfile(EXECUTION, target / "_execution.py")
    shutil.copyfile(ERRORS, target / "errors.py")
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append(file["path"])
        return original(file)
    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(parsed) == ([] if not (repo / "src/noise_7.py").exists() else
                              ["src/trpg_state_machine/_execution.py", "src/trpg_state_machine/errors.py"])
    assert updated["simple_python_certificate"] is None
    assert updated["value_flow_coverage"] == "source-only-no-target-certificate"
    folder, _ = manifest(config, updated["version"])
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        assert db.execute("select count(*) from simple_python_certificates").fetchone()[0] == 0
    full_config = dict(config, data=str(tmp_path / "fresh"))
    fresh = build(full_config, offline=True, lexical_only=True)
    assert updated["simple_python_certificate"] == fresh["simple_python_certificate"]
    assert_semantic_equal(full_semantic(config, updated["version"]),
                          full_semantic(full_config, fresh["version"]))
    parsed.clear()
    identical = build(config, offline=True, lexical_only=True)
    assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
    assert identical["simple_python_certificate"] is None
    assert identical["value_flow_coverage"] == "source-only-no-target-certificate"
    source = target / "_execution.py"
    source.write_bytes(source.read_bytes().replace(b'"actor"', b'"actor_changed"', 1))
    later = build(config, offline=True, lexical_only=True)
    assert later["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert later["simple_python_certificate"] is None
    assert later["value_flow_coverage"] == "source-only-no-target-certificate"
    fresh_later_config = dict(config, data=str(tmp_path / "fresh-later"))
    fresh_later = build(fresh_later_config, offline=True, lexical_only=True)
    assert semantic(config, later["version"]) == semantic(fresh_later_config, fresh_later["version"])
