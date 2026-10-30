"""Cross-repository bounded preparation has the same graph as a fresh capture."""

import json
import sqlite3
import subprocess

from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def fixture(tmp_path, *, pinned=False, local_shadow=False):
    config, consumer = initialize(tmp_path / "fixture")
    (consumer / "src/weights.py").unlink()
    provider = tmp_path / "provider"
    source = provider / "src/dnd5e_engine"
    source.mkdir(parents=True)
    (source / "evaluation.py").write_text("def target(): pass\n")
    (source / "unrelated.py").write_text("def idle(): pass\n")
    if local_shadow:
        own = consumer / "src/dnd5e_engine"
        own.mkdir()
        (own / "evaluation.py").write_text("def target(): pass\n")
    for args in (("init",), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid"),
                 ("add", "."), ("-c", "commit.gpgsign=false", "commit", "-m", "initial")):
        subprocess.run(("git", *args), cwd=provider, check=True, capture_output=True)
    head = subprocess.run(("git", "rev-parse", "HEAD"), cwd=provider,
                          check=True, capture_output=True, text=True).stdout.strip()
    if pinned:
        (consumer / "pyproject.toml").write_text(
            '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="'
            + head + '"}\n')
    config["repositories"].append(dict(name="trpg-rules-engine", path=str(provider),
                                        code_roots=["src"]))
    return config, consumer, provider


def records(config, version):
    folder, _ = manifest(config, version)
    output = {}
    for database, tables in (("catalog.sqlite", ("nodes", "edges")),
                             ("graph-sites.sqlite", ("sites", "query_observations",
                                                     "import_dependencies", "import_requests"))):
        with sqlite3.connect(folder / database) as connection:
            for table in tables:
                output[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                       for row in connection.execute(f"select data from {table}"))
    return output


def same_as_full(config, updated, tmp_path):
    oracle_config = dict(config, data=str(tmp_path / "oracle"))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(oracle_config, oracle["version"])


def test_two_independent_repositories_with_same_path_reuse_other_owner(tmp_path):
    config, consumer, provider = fixture(tmp_path)
    (consumer / "src/dnd5e_engine").mkdir()
    (consumer / "src/dnd5e_engine/evaluation.py").write_text("def target(): pass\n")
    (consumer / "src/caller.py").write_text("def run(): target()\ndef target(): pass\n")
    build(config, offline=True, lexical_only=True)
    (provider / "src/dnd5e_engine/evaluation.py").write_text("def target(): return 1\n")
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "certified-simple-python-component"
    assert scope["python_files_parsed"] == 1
    same_as_full(config, updated, tmp_path)


def test_new_local_import_expands_closure_without_parsing_unrelated_repo(tmp_path):
    config, consumer, provider = fixture(tmp_path)
    (consumer / "src/caller.py").write_text("def run(): pass\n")
    build(config, offline=True, lexical_only=True)
    (consumer / "src/caller.py").write_text(
        "from helper import target\ndef run(): target()\n")
    (consumer / "src/helper.py").write_text("def target(): pass\n")
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "certified-simple-python-component"
    assert scope["python_files_parsed"] == 2
    same_as_full(config, updated, tmp_path)


def test_exact_pinned_cross_repository_import_and_local_precedence(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    caller = consumer / "src/caller.py"
    caller.write_text("from dnd5e_engine.evaluation import target\ndef run(): target()\n")
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["graph"]["dependency_bindings"]["synthetic-review"]["matched"]
    caller.write_text(caller.read_text() + "def second(): target()\n")
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "certified-simple-python-component"
    assert scope["python_files_parsed"] == 2
    same_as_full(config, updated, tmp_path)

    # With a captured local module of the same name, the graph's local-first
    # import decision must remain local, even under a matched dependency pin.
    local = consumer / "src/dnd5e_engine/evaluation.py"
    local.parent.mkdir(exist_ok=True)
    local.write_text("def target(): pass\n")
    local_result = build(config, offline=True, lexical_only=True)
    assert local_result["incremental"]["analysis_scope"]["mode"] == "certified-simple-python-component"
    same_as_full(config, local_result, tmp_path / "shadow")


def test_binding_change_and_unmatched_pin_fall_back(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    caller = consumer / "src/caller.py"
    caller.write_text("from dnd5e_engine.evaluation import target\ndef run(): target()\n")
    build(config, offline=True, lexical_only=True)
    (provider / "src/dnd5e_engine/evaluation.py").write_text("def target(): return 1\n")
    updated = build(config, offline=True, lexical_only=True)
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert updated["incremental"]["analysis_scope"]["reason"] == "dependency-bindings-changed"
    assert not updated["graph"]["dependency_bindings"]["synthetic-review"]["matched"]
    same_as_full(config, updated, tmp_path)


def test_removed_local_shadow_reanalyzes_requester_and_pinned_provider(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True, local_shadow=True)
    caller = consumer / "src/caller.py"
    caller.write_text("from dnd5e_engine.evaluation import target as action\ndef run(): action()\n")
    build(config, offline=True, lexical_only=True)
    (consumer / "src/dnd5e_engine/evaluation.py").unlink()
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "certified-simple-python-component"
    assert scope["python_files_parsed"] == 2
    same_as_full(config, updated, tmp_path)


def test_reverse_requester_lookup_has_indexed_plan(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    (consumer / "src/caller.py").write_text(
        "from dnd5e_engine.evaluation import target as action\ndef run(): action()\n")
    original = build(config, offline=True, lexical_only=True)
    folder, prior = manifest(config, original["version"])
    with FileDependencies(folder, prior) as dependencies:
        assert dependencies.requesters("synthetic-review", "dnd5e_engine.evaluation") == {
            ("synthetic-review", "src/caller.py")}
        assert dependencies.importers("trpg-rules-engine", "dnd5e_engine.evaluation") == {
            ("synthetic-review", "src/caller.py")}
        plan = list(dependencies.db.execute(
            "explain query plan select source_repository,source_path from import_requests "
            "where source_repository=? and requested_module=?",
            ("synthetic-review", "dnd5e_engine.evaluation")))
        assert any("import_request_requester" in row[3] for row in plan), plan
        assert dependencies.has_descendant_requesters("synthetic-review", "dnd5e_engine")
        ancestor_plan = list(dependencies.db.execute(
            "explain query plan select 1 from import_requests where source_repository=? "
            "and requested_module>=? and requested_module<? limit 1",
            ("synthetic-review", "dnd5e_engine.", "dnd5e_engine/")))
        assert any("import_request_requester" in row[3] for row in ancestor_plan), ancestor_plan


def test_package_initializer_shadow_changes_fall_back(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    (consumer / "src/caller.py").write_text(
        "from dnd5e_engine.evaluation import target\ndef run(): target()\n")
    build(config, offline=True, lexical_only=True)
    package = consumer / "src/dnd5e_engine"
    package.mkdir()
    initializer = package / "__init__.py"
    initializer.write_text("")
    added = build(config, offline=True, lexical_only=True)
    assert added["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert added["incremental"]["analysis_scope"]["reason"] == "package-initializer-changed"
    same_as_full(config, added, tmp_path)
    initializer.unlink()
    removed = build(config, offline=True, lexical_only=True)
    assert removed["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert removed["incremental"]["analysis_scope"]["reason"] == "package-initializer-changed"
    same_as_full(config, removed, tmp_path / "removed")


def test_ancestor_module_shadow_changes_fall_back(tmp_path):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    (consumer / "src/caller.py").write_text(
        "from dnd5e_engine.evaluation import target\ndef run(): target()\n")
    build(config, offline=True, lexical_only=True)
    shadow = consumer / "src/dnd5e_engine.py"
    shadow.write_text("def unrelated(): pass\n")
    added = build(config, offline=True, lexical_only=True)
    assert added["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert added["incremental"]["analysis_scope"]["reason"] == "ancestor-module-layout-changed"
    same_as_full(config, added, tmp_path)
    shadow.unlink()
    removed = build(config, offline=True, lexical_only=True)
    assert removed["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert removed["incremental"]["analysis_scope"]["reason"] == "ancestor-module-layout-changed"
    same_as_full(config, removed, tmp_path / "removed")
