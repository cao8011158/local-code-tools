"""Test quota handling, incremental lexical writes and publication boundaries."""

import sqlite3
import subprocess
import sys
import tomllib
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from filelock import Timeout

from lct import cgr_cli, cgr_runtime
from lct.cgr_cli import register_codex
from lct.cgr_config import Config, Repository, load_config
from lct.cgr_lexical import candidates, connect, publish, refresh_docs, require_ready, sync_entries
from lct.cgr_runtime import merge_rankings


def test_refresh_and_search_use_pinned_model_and_workspace_worker(tmp_path):
    """Bind the model snapshot to its pin and the worker to its index directory."""
    path = tmp_path / "workspace.toml"
    path.write_text(
        'name = "example"\nindex_dir = "index"\nmodel_cache = "models"\n'
        '[repositories.APP]\nkind = "code"\npath = "."\n',
        encoding="utf-8",
    )
    config = load_config(path)
    env = cgr_runtime.cgr_environment(config)
    revision = env["CGR_EMBEDDING_REVISION"]
    snapshot = Path(env["CGR_UNIXCODER_MODEL_PATH"])
    assert revision == cgr_runtime.MODEL_REVISION == snapshot.name
    assert snapshot.parent.name == "snapshots"
    assert snapshot.is_relative_to(config.model_cache)
    worker = Path(env["CGR_UNIXCODER_WORKER_DIR"])
    assert worker == config.data / "embedding-worker"
    other = replace(config, data=tmp_path / "other-index")
    assert Path(cgr_runtime.cgr_environment(other)["CGR_UNIXCODER_WORKER_DIR"]) != worker
    assert "CGR_EMBEDDING_LEGACY_REVISION" not in env


def test_mcp_registration_renames_existing_workspace(tmp_path, monkeypatch):
    """Rename the managed MCP pair without changing its workspace or unrelated servers."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    project = tmp_path / "project.toml"
    project.write_text(
        'name = "example"\nindex_dir = "index"\nmodel_cache = "models"\n'
        '[repositories.APP]\nkind = "code"\npath = "."\n',
        encoding="utf-8",
    )
    initial = load_config(project)
    assert initial.mcp_prefix == "lct_example"
    codex_config = tmp_path / "config.toml"
    codex_config.write_text('[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")
    register_codex(initial)
    renamed = replace(initial, mcp_prefix="lct")
    register_codex(renamed)
    result = codex_config.read_bytes()
    servers = tomllib.loads(result.decode("utf-8"))["mcp_servers"]
    assert set(servers) == {"other", "lct_graph", "lct_search"}
    assert set(servers["lct_graph"]["enabled_tools"]) == {
        "resolve",
        "definition",
        "context",
        "callers",
        "callees",
        "list_projects",
    }
    assert servers["lct_graph"]["args"][-2:] == ["--workspace", "example"]
    assert servers["lct_search"]["args"][-1] == str(project)
    assert renamed.index_identity() == initial.index_identity()
    register_codex(renamed)
    assert codex_config.read_bytes() == result
    unrelated = replace(
        renamed,
        path=tmp_path / "other.toml",
        data=tmp_path / "other-index",
        mcp_prefix="other",
    )
    with pytest.raises(ValueError, match="workspace is already registered"):
        register_codex(unrelated)
    assert codex_config.read_bytes() == result


def test_index_repository_additive_failure_and_retry(tmp_path, monkeypatch):
    """Keep existing identities fixed and make a failed new build retryable."""
    for name in ("sm", "re", "docs", "agents"):
        (tmp_path / name).mkdir()
    subprocess.run(["git", "init", "-q", str(tmp_path / "agents")], check=True)
    project = tmp_path / "project.toml"
    project.write_text(
        'name = "example"\nindex_dir = "index"\nmodel_cache = "models"\n'
        '[repositories.SM]\nkind = "code"\nname = "state-machine"\npath = "sm"\n'
        '[repositories.RE]\nkind = "code"\nname = "rules-engine"\npath = "re"\n'
        '[repositories.DOC]\nkind = "docs"\npath = "docs"\n',
        encoding="utf-8",
    )
    config = load_config(project)
    cgr_runtime.bind_indexes(config)
    original = dict(config.repositories)
    calls = []

    def refresh(_config, alias):
        """Record the requested alias and fail only the first build."""
        calls.append((tuple(_config.repositories), alias))
        ok = len(calls) > 1
        if ok:
            with cgr_runtime.database(_config, alias) as db, db:
                publish(db, alias, "ready", {"nodes": 0})
        return {"ok": ok, "project": alias}

    saved = []
    save_manifest = cgr_cli.save_cgr_workspace

    def record_manifest(current):
        """Record each manifest write while keeping its actual effect."""
        saved.append(current)
        return save_manifest(current)

    monkeypatch.setattr(cgr_cli, "refresh", refresh)
    monkeypatch.setattr(cgr_cli, "save_cgr_workspace", record_manifest)
    monkeypatch.setattr(cgr_cli, "ensure_model", lambda current: None)
    monkeypatch.setattr(cgr_cli, "ensure_qdrant", lambda current: "reused")
    path = str((tmp_path / "agents").resolve())
    first = cgr_cli.register_repository(config, "example", path, "trpg-agents")
    assert first == {"ok": False, "project": "trpg-agents"}
    assert not saved
    after_failure = load_config(project)
    assert after_failure.repositories["trpg-agents"].path == Path(path)
    assert {key: after_failure.repositories[key] for key in original} == original
    assert config.index_identity() == (tmp_path / "index" / "identity.json").read_text()
    assert after_failure.index_identity() == config.index_identity()
    assert after_failure.added_repositories == ("trpg-agents",)
    manifest = save_manifest(after_failure)
    assert {
        repo["project_name"] for repo in tomllib.loads(manifest.read_text())["workspace"]["repos"]
    } == {
        "state-machine",
        "rules-engine",
    }
    with closing(connect(tmp_path / "index" / "code.sqlite")) as db, db:
        for alias in ("SM", "RE"):
            sync_entries(
                db,
                alias,
                {
                    alias: (
                        1,
                        "file.py",
                        "baseline marker",
                        {
                            "project": alias,
                            "qualified_name": alias,
                        },
                    )
                },
            )
            publish(db, alias, "ready", {"nodes": 1})
    embedder = ModuleType("codebase_rag.embedder")
    embedder._unixcoder_embed_code = lambda query, _: [0.0]
    monkeypatch.setitem(sys.modules, "codebase_rag.embedder", embedder)
    monkeypatch.setattr(cgr_runtime, "configure", lambda _: None)
    monkeypatch.setattr(
        cgr_runtime,
        "qdrant",
        lambda: SimpleNamespace(query_points=lambda **kwargs: SimpleNamespace(points=[])),
    )
    assert {hit["project"] for hit in cgr_runtime.hybrid_search(after_failure, "marker")} == {
        "SM",
        "RE",
    }
    with pytest.raises(RuntimeError, match="trpg-agents unavailable"):
        cgr_runtime.hybrid_search(after_failure, "marker", project="trpg-agents")
    second = cgr_cli.register_repository(config, "example", path, "trpg-agents")
    assert second["ok"] and second["graph_mcp_restart_required"]
    assert len(saved) == 1 and set(saved[0].repositories) == {*original, "trpg-agents"}
    assert calls == [(tuple(after_failure.repositories), "trpg-agents")] * 2
    with closing(connect(tmp_path / "index" / "code.sqlite")) as db, db:
        publish(db, "trpg-agents", "ready", {"nodes": 0})
    third = cgr_cli.register_repository(config, "example", path, "trpg-agents")
    assert third["already_indexed"] and not third["graph_mcp_restart_required"]
    assert len(calls) == 2 and len(saved) == 2
    assert load_config(project).published_repositories == ("trpg-agents",)
    with closing(connect(tmp_path / "index" / "code.sqlite")) as db, db:
        publish(db, "trpg-agents", "failed", {"error": "later refresh failed"})
    cgr_cli.save_cgr_workspace(load_config(project))
    assert saved[-1].published_repositories == ("trpg-agents",)
    manifest = save_manifest(load_config(project))
    assert {
        repo["project_name"] for repo in tomllib.loads(manifest.read_text())["workspace"]["repos"]
    } == {
        "state-machine",
        "rules-engine",
        "trpg-agents",
    }
    with pytest.raises(ValueError, match="different identity"):
        cgr_cli.register_repository(config, "example", path, "other", "trpg-agents")
    with pytest.raises(ValueError, match="already registered"):
        cgr_cli.register_repository(config, "example", path, "trpg-agents", "OTHER")
    assert set(load_config(project).repositories) == {*original, "trpg-agents"}
    (tmp_path / "agents").rename(tmp_path / "agents-away")
    without_checkout = load_config(project)
    assert {hit["project"] for hit in cgr_runtime.hybrid_search(without_checkout, "marker")} == {
        "SM",
        "RE",
    }
    assert cgr_runtime.refresh_index(without_checkout, "trpg-agents")["stage"] == "checkout"
    project.write_text(
        project.read_text().replace(
            '[repositories.RE]\nkind = "code"\nname = "rules-engine"\npath = "re"\n', ""
        )
    )
    with pytest.raises(ValueError, match="registry does not match"):
        load_config(project)


@pytest.fixture
def registration_workspace(tmp_path, monkeypatch):
    """Create an isolated code workspace and bypass service setup."""
    (tmp_path / "core").mkdir()
    checkout = tmp_path / "new-repo"
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    path = tmp_path / "workspace.toml"
    path.write_text(
        'name = "example"\nindex_dir = "index"\nmodel_cache = "models"\n'
        '[repositories.CORE]\nkind = "code"\npath = "core"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    cgr_runtime.bind_indexes(config)
    monkeypatch.setattr(cgr_cli, "ensure_model", lambda current: None)
    monkeypatch.setattr(cgr_cli, "ensure_qdrant", lambda current: "reused")
    return config, str(checkout)


def test_registration_repairs_manifest_and_signals_restart_after_save_failure(
    registration_workspace, monkeypatch
):
    """Retry an already-ready build after an interrupted manifest publication."""
    config, checkout = registration_workspace
    args = config, config.name, checkout, "new-repo"
    saved = []
    builds = []
    save_manifest = cgr_cli.save_cgr_workspace
    save_manifest(config)
    embedder = ModuleType("codebase_rag.embedder")
    embedder._unixcoder_embed_code = lambda query, _: [0.0]
    monkeypatch.setitem(sys.modules, "codebase_rag.embedder", embedder)
    monkeypatch.setattr(cgr_runtime, "configure", lambda _: None)
    monkeypatch.setattr(
        cgr_runtime,
        "qdrant",
        lambda: SimpleNamespace(query_points=lambda **kwargs: SimpleNamespace(points=[])),
    )

    def publish_fixture(current, alias, node_id):
        """Expose one ready node through the real code BM25 database."""
        with cgr_runtime.guard(current, alias), cgr_runtime.database(current, alias) as db, db:
            sync_entries(
                db,
                alias,
                {
                    alias: (
                        node_id,
                        "file.py",
                        "manifest fixture",
                        {"project": alias, "qualified_name": f"{alias}.fixture"},
                    )
                },
            )
            publish(db, alias, "ready", {"nodes": 1})

    publish_fixture(config, "CORE", 1)

    def refresh(current, alias):
        """Create a ready lexical publication for the one simulated build."""
        builds.append(alias)
        publish_fixture(current, alias, 2)
        return {"ok": True, "project": alias}

    def fail_once(current):
        """Require the code guard during manifest writes and fail the first write."""
        with pytest.raises(Timeout), cgr_runtime.guard(current, "new-repo"):
            pytest.fail("manifest write raced with code refresh")
        saved.append(current)
        if len(saved) == 1:
            raise OSError("workspace save failed")
        return save_manifest(current)

    monkeypatch.setattr(cgr_cli, "refresh", refresh)
    monkeypatch.setattr(cgr_cli, "save_cgr_workspace", fail_once)
    with pytest.raises(OSError, match="workspace save failed"):
        cgr_cli.register_repository(*args)
    partially_published = load_config(config.path)
    assert partially_published.published_repositories == ("new-repo",)
    assert cgr_runtime.published_graph_members(partially_published) == ()
    assert [
        hit["project"] for hit in cgr_runtime.hybrid_search(partially_published, "fixture")
    ] == ["CORE"]
    with pytest.raises(RuntimeError, match="graph workspace publication is incomplete"):
        cgr_runtime.hybrid_search(partially_published, "fixture", project="new-repo")

    result = cgr_cli.register_repository(*args)
    assert result["ok"] and result["already_indexed"] and result["graph_mcp_restart_required"]
    current = load_config(config.path)
    assert cgr_runtime.published_graph_members(current) == ("new-repo",)
    assert {hit["project"] for hit in cgr_runtime.hybrid_search(current, "fixture")} == {
        "CORE",
        "new-repo",
    }
    assert [
        hit["project"] for hit in cgr_runtime.hybrid_search(current, "fixture", project="new-repo")
    ] == ["new-repo"]
    repeat = cgr_cli.register_repository(*args)
    assert repeat["ok"] and repeat["already_indexed"] and not repeat["graph_mcp_restart_required"]
    assert builds == ["new-repo"]
    Path(checkout).rename(Path(checkout).with_name("checkout-away"))
    missing_checkout = load_config(config.path)
    assert [
        hit["project"]
        for hit in cgr_runtime.hybrid_search(missing_checkout, "fixture", project="new-repo")
    ] == ["new-repo"]


def test_registration_does_not_publish_if_another_refresh_invalidates_readiness(
    registration_workspace, monkeypatch
):
    """Reject manifest publication when a later refresh wins the code guard."""
    config, checkout = registration_workspace

    def refreshed_then_invalidated(current, alias):
        """Interleave the second refresh before the first caller can publish."""
        with cgr_runtime.guard(current, alias), cgr_runtime.database(current, alias) as db, db:
            publish(db, alias, "ready", {"nodes": 0})
        with cgr_runtime.guard(current, alias), cgr_runtime.database(current, alias) as db, db:
            publish(db, alias, "failed", {"error": "superseding refresh failed"})
        return {"ok": True, "project": alias}

    monkeypatch.setattr(cgr_cli, "refresh", refreshed_then_invalidated)
    with pytest.raises(RuntimeError, match="superseding refresh failed"):
        cgr_cli.register_repository(config, config.name, checkout, "new-repo")
    current = load_config(config.path)
    assert current.added_repositories == ("new-repo",)
    assert current.published_repositories == ()
    assert cgr_runtime.published_graph_members(current) == ()


def test_hybrid_quota_and_backfill():
    """Overlapping BM25 hits leave the exclusive BM25 slot open."""
    ranked = merge_rankings(list("ABCDE"), list("BDF"), 5)
    assert ranked == [
        ("A", "vector", ["vector"]),
        ("B", "vector", ["vector", "bm25"]),
        ("C", "vector", ["vector"]),
        ("D", "vector", ["vector", "bm25"]),
        ("F", "bm25", ["bm25"]),
    ]
    assert [k for k, _, _ in merge_rankings(list("AAB"), list("ABXYZ"), 5)] == list("ABXYZ")
    assert [k for k, _, _ in merge_rankings(list("ABCDE"), list("BD"), 5)] == list("ABCDE")
    assert [k for k, _, _ in merge_rankings(list("ABCD"), list("X"), 4)] == list("ABCD")
    ranked = merge_rankings(list("ABCDEFGHIJ"), list("AXY"), 10)
    assert [key for key, slot, _ in ranked if slot == "bm25"] == list("XY")
    ranked = merge_rankings(range(150), range(150, 200), 123)
    assert len(ranked) == 123
    assert sum(slot == "bm25" for _, slot, _ in ranked) == 24


def test_hybrid_search_routes_cgr_names_before_colliding_aliases(tmp_path, monkeypatch):
    """Search routes official names to the right lexical scope and vector filter."""
    repositories = {
        "SM": Repository(tmp_path, "code", "trpg-state-machine", (), ()),
        "trpg-state-machine": Repository(tmp_path, "code", "rules-engine", (), ()),
    }
    config = Config(
        tmp_path / "config.toml",
        "example",
        tmp_path,
        tmp_path / "models",
        "http://127.0.0.1:6333",
        None,
        None,
        repositories,
        "lct",
    )
    with closing(connect(tmp_path / "code.sqlite")) as db, db:
        for alias, repo in repositories.items():
            sync_entries(
                db,
                alias,
                {
                    alias: (
                        1,
                        "file.py",
                        "shared token",
                        {
                            "project": alias,
                            "graph_project": repo.name,
                            "qualified_name": f"{alias}.function",
                        },
                    ),
                },
            )
            publish(db, alias, "ready", {"nodes": 1})

    embedder = ModuleType("codebase_rag.embedder")
    embedder._unixcoder_embed_code = lambda query, _: [0.0]
    monkeypatch.setitem(sys.modules, "codebase_rag.embedder", embedder)
    monkeypatch.setattr(cgr_runtime, "configure", lambda _: None)
    monkeypatch.setattr(
        cgr_runtime,
        "published_graph_members",
        lambda _: pytest.fail("configured projects should not read the graph manifest"),
    )
    seen_filters = []

    def query_points(**kwargs):
        """Capture the server-side project filter while leaving lexical hits visible."""
        seen_filters.append(kwargs["query_filter"].must[0].match.any)
        return SimpleNamespace(points=[])

    monkeypatch.setattr(cgr_runtime, "qdrant", lambda: SimpleNamespace(query_points=query_points))
    for requested, expected_alias, expected_filter in (
        ("trpg-state-machine", "SM", ["trpg-state-machine"]),
        ("SM", "SM", ["trpg-state-machine"]),
        ("rules-engine", "trpg-state-machine", ["rules-engine"]),
    ):
        hits = cgr_runtime.hybrid_search(config, "shared", project=requested)
        assert [(hit["project"], hit["graph_project"]) for hit in hits] == [
            (expected_alias, expected_filter[0])
        ]
        assert seen_filters[-1] == expected_filter
    hits = cgr_runtime.hybrid_search(config, "shared")
    assert {hit["project"] for hit in hits} == set(repositories)
    assert seen_filters[-1] == ["trpg-state-machine", "rules-engine"]
    with pytest.raises(ValueError, match="list_projects"):
        cgr_runtime.hybrid_search(config, "shared", project="missing")


def test_code_changes_and_scope(tmp_path):
    """A graph id or location change does not retokenize an unchanged docstring."""
    with closing(connect(tmp_path / "lexical.sqlite")) as db:

        def node(id_, text, line):
            """Create a minimal code record with a distinct location."""
            return id_, "file.py", text, {"line": line}

        sync_entries(db, "SM", {"a": node(1, "alpha original", 1), "b": node(2, "deleted", 2)})
        sync_entries(db, "RE", {"a": node(1, "alpha original", 8)})
        assert sync_entries(
            db,
            "SM",
            {
                "a": node(8, "alpha original", 4),
                "c": node(9, "introduced", 6),
            },
        ) == {"inserted": 1, "replaced": 0, "relocated": 1, "deleted": 1}
        assert not candidates(db, "deleted", 5, ["SM"])
        assert [row["node_id"] for row in candidates(db, "original", 5, ["SM"])] == [8]
        assert [row["node_id"] for row in candidates(db, "original", 5, ["RE"])] == [1]
        assert sync_entries(
            db,
            "SM",
            {
                "a": node(8, "alpha revised", 4),
                "c": node(9, "introduced", 6),
            },
        ) == {"inserted": 0, "replaced": 1, "relocated": 0, "deleted": 0}
        assert not candidates(db, "original", 5, ["SM"])
        assert [row["node_id"] for row in candidates(db, "revised", 5, ["SM"])] == [8]
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT metadata FROM entry WHERE project=? AND node_id=?",
            ("SM", 8),
        ).fetchone()
        assert "SEARCH entry USING INDEX" in plan[3]


def test_markdown_delta_and_rollback(tmp_path: Path):
    """Read dirty Markdown, only parse changed files and retain old rows on failure."""
    docs = tmp_path / "docs"
    docs.mkdir()
    file = docs / "contract.md"
    file.write_text("# Keep\noriginalmarker\n## Remove\ndeletedmarker\n", encoding="utf-8")
    (docs / "untouched.md").write_text(
        "Another title\n=============\nRetainedToken", encoding="utf-8"
    )
    repo = Repository(tmp_path, "docs", "doc", (), ())
    with closing(connect(tmp_path / "docs.sqlite")) as db:
        with db:
            assert refresh_docs(db, "DOC", repo)["sections"] == 3
        file.write_text("# Keep\nmodifiedmarker\n## Add\nnewmarker\n", encoding="utf-8")
        with db:
            result = refresh_docs(db, "DOC", repo)
        assert result["file_changes"] == {"modified": 1}
        assert result["section_changes"] == {
            "inserted": 1,
            "replaced": 1,
            "relocated": 0,
            "deleted": 1,
        }
        assert not candidates(db, "deletedmarker", 5, ["DOC"], "contract")
        assert candidates(db, "newmarker", 5, ["DOC"], "contract")
        before = db.total_changes
        with db:
            assert refresh_docs(db, "DOC", repo)["file_changes"] == {}
        assert db.total_changes == before

        with db:
            publish(db, "DOC", "refreshing", "interrupted")
        with pytest.raises(RuntimeError, match="interrupted"):
            require_ready(db, ["DOC"])
        with pytest.raises(sqlite3.IntegrityError), db:
            db.execute("DELETE FROM entry WHERE project='DOC'")
            db.execute("INSERT INTO doc_file VALUES (?,?)", ("docs/contract.md", "duplicate"))
        assert db.execute("SELECT count(*) FROM entry").fetchone()[0] == 3
