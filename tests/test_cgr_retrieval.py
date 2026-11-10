"""Test quota handling, incremental lexical writes and publication boundaries."""

import sqlite3
import sys
import tomllib
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from lct import cgr_runtime
from lct.cgr_cli import register_codex
from lct.cgr_config import Config, Repository, load_config
from lct.cgr_lexical import candidates, connect, publish, refresh_docs, require_ready, sync_entries
from lct.cgr_runtime import merge_rankings


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
