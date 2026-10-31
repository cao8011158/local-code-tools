"""Independent public-build checks for the bounded 4B context/reuse slice."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import lct.extract as extraction
from lct.common import ToolError
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize


FIXTURES = Path(__file__).parent / "fixtures"


def capture(tmp_path):
    config, repo = initialize(tmp_path / "owned")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    package = repo / "src/trpg_state_machine"
    package.mkdir()
    shutil.copyfile(FIXTURES / "actual-related-source/src/trpg_state_machine/_execution.py",
                    package / "_execution.py")
    shutil.copyfile(FIXTURES / "actual-source-subset/src/trpg_state_machine/errors.py",
                    package / "errors.py")
    for index in range(20):
        (repo / f"src/idle_{index}.py").write_text(f"def idle_{index}():\n    return {index}\n")
    return config, repo, package / "_execution.py"


def semantic_tables(config, version):
    folder, _ = manifest(config, version)
    answer = {}
    for filename in ("catalog.sqlite", "graph-sites.sqlite"):
        with sqlite3.connect(folder / filename) as database:
            for (table,) in database.execute("select name from sqlite_master where type='table'"):
                # These are search materializations / runtime metadata rather than graph evidence.
                if table not in {"nodes", "edges", "sites", "query_observations",
                                 "import_requests", "import_dependencies", "analysis_reads",
                                 "analysis_watches", "analysis_input_scopes", "analysis_input_members",
                                 "analysis_input_consumers", "value_nodes", "value_edges", "value_reads",
                                 "passive_python_certificates"}:
                    continue
                columns = [row[1] for row in database.execute(f'pragma table_info("{table}")')]
                rows = []
                for row in database.execute(f'select * from "{table}"'):
                    rows.append([json.loads(value) if column == "data" else value
                                 for column, value in zip(columns, row)])
                answer[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
    return answer


@pytest.mark.parametrize("operation", ["new-provider", "delete-provider", "change-to-active"])
def test_general_reuse_preserves_future_deleted_and_newly_active_providers(tmp_path, monkeypatch, operation):
    config, repo, source = capture(tmp_path)
    if operation in {"new-provider", "delete-provider"}:
        source.write_bytes(source.read_bytes() + b"\nfrom future_module import chosen\nchosen()\n")
    if operation == "delete-provider":
        (repo / "src/future_module.py").write_text("def chosen():\n    return 1\n")
    previous = build(config, offline=True, lexical_only=True)
    old_records = semantic_tables(config, previous["version"])
    if operation == "new-provider":
        (repo / "src/future_module.py").write_text("def chosen():\n    return 2\n")
    elif operation == "delete-provider":
        (repo / "src/future_module.py").unlink()
    else:
        (repo / "src/idle_7.py").write_text("def next_target():\n    return 3\ndef idle_7():\n    return next_target()\n")
    parsed = []
    original = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph", scope
    assert len(set(parsed)) == scope["python_ast_context_files"]
    assert "src/idle_19.py" in parsed
    assert scope["python_ast_context_files"] == (23 if operation == "new-provider" else 22)
    assert scope["context_source_files"] == 0
    assert semantic_tables(config, previous["version"]) == old_records
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert semantic_tables(config, updated["version"]) == semantic_tables(fresh_config, fresh["version"])


def test_general_second_update_keeps_receipts_and_failed_candidate_keeps_old_pointer(tmp_path):
    config, repo, source = capture(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    first_records = semantic_tables(config, first["version"])
    source.write_bytes(source.read_bytes().replace(b'"actor"', b'"first_edit"', 1))
    second = build(config, offline=True, lexical_only=True)
    assert second["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    source.write_bytes(source.read_bytes().replace(b'"first_edit"', b'"second_edit"', 1))
    old = semantic_tables(config, second["version"])
    with pytest.raises(ToolError, match="Injected interruption"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == second["version"]
    assert semantic_tables(config, second["version"]) == old
    third = build(config, offline=True, lexical_only=True)
    assert third["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    # The fixture retains two activations; the oldest may now be intentionally pruned.
    assert first_records != semantic_tables(config, third["version"])
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert semantic_tables(config, third["version"]) == semantic_tables(fresh_config, fresh["version"])


def test_changed_initializer_remains_explicit_full_fallback(tmp_path):
    config, repo, source = capture(tmp_path)
    first = build(config, offline=True, lexical_only=True)
    (source.parent / "__init__.py").write_text('"""New initializer may change imports."""\n')
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph", scope
    assert scope["reason"] == "python-membership-changed", scope
    assert first["version"] != updated["version"]


def test_plain_import_requires_real_context_expansion_and_no_error_downgrade(tmp_path, monkeypatch):
    import lct.python_analysis as analysis

    config, repo, source = capture(tmp_path)
    build(config, offline=True, lexical_only=True)
    source.write_bytes(source.read_bytes() + b"\nimport idle_7\nidle_7.idle_7()\n")
    expanded = []
    original_map = analysis.Analyzer.map_name

    def observed(self, name):
        try:
            return original_map(self, name)
        except analysis.RequiredAnalysisContext as required:
            expanded.append((required.repository, required.path))
            raise

    monkeypatch.setattr(analysis.Analyzer, "map_name", observed)
    parsed = []
    original_extract = extraction.python_nodes

    def counted(file):
        parsed.append(file["path"])
        return original_extract(file)

    monkeypatch.setattr(extraction, "python_nodes", counted)
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "full-graph", scope
    assert expanded == []  # full build already carries the entire captured AST context
    assert sorted(parsed) == sorted(["src/trpg_state_machine/_execution.py"] + [str(p.relative_to(repo)) for p in (repo / "src").rglob("*.py")])
    fresh_config = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert semantic_tables(config, updated["version"]) == semantic_tables(fresh_config, fresh["version"])
