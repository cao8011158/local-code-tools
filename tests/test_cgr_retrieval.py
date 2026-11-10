"""Test quota handling, incremental lexical writes and publication boundaries."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from lct.cgr_config import Repository
from lct.cgr_lexical import candidates, connect, publish, refresh_docs, require_ready, sync_entries
from lct.cgr_runtime import merge_rankings


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
