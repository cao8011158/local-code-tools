"""Version, mutation, rollback, cursor and backup acceptance in an isolated Git fixture."""

import copy
import subprocess
from pathlib import Path

import pytest

from lct.common import ROOT, ToolError, atomic, config
from lct.management import backup, restore
from lct.query import Query
from lct.storage import build, current, manifest, recover, validate_folder


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "sample"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Local Acceptance"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "local-acceptance@example.invalid"],
        check=True,
    )
    (root / "src/sample.py").write_text(
        '"""Sample module."""\nclass Box:\n """Container."""\n def weight(self):\n  """容器重量 total weight."""\n  return helper()\ndef helper():\n """Compute weight."""\n return 1\n',
        encoding="utf-8",
    )
    (root / "docs/guide.md").write_text("# Contract\n容器重量 SQLite 发布。\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "src/sample.py", "docs/guide.md"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "fixture"], check=True, capture_output=True
    )
    c = copy.deepcopy(config())
    c["repositories"] = [dict(name="sample", path=str(root), code_roots=["src"])]
    c["data"] = str(tmp_path / "data")
    c["_path"] = str(tmp_path / "config.json")
    c["embedding"]["historical_cache"] = "none"
    atomic(c["_path"], {k: v for k, v in c.items() if not k.startswith("_")})
    return c, root


def test_mutations_cursor_failure_recovery(sandbox, monkeypatch):
    c, root = sandbox
    first = build(c, lexical_only=True)
    q = Query(c)
    result = q.search_code("weight", mode="bm25", candidates=10, limit=1)
    assert result["has_more"]
    cursor = result["next_cursor"]
    nid = result["results"][0]["node_id"]
    assert q.get_nodes([nid])["nodes"][0]["live_file_matches"]
    source = root / "src/sample.py"
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("return 1", "return 2"), encoding="utf-8")
    (root / "src/new.py").write_text(
        'def added():\n """weight added."""\n return 3\n', encoding="utf-8"
    )
    second = build(c, lexical_only=True)
    assert second["incremental"]["nodes_updated"] > 0
    assert (
        q.search_code("weight", mode="bm25", candidates=10, limit=1, cursor=cursor)["version"]
        == first["version"]
    )
    with pytest.raises(ToolError, match="conditions"):
        q.search_code("changed query", mode="bm25", candidates=10, limit=1, cursor=cursor)
    old = q.get_nodes([nid], version=first["version"])["nodes"][0]
    assert not old["live_file_matches"]
    assert old["source_origin"] == "indexed_snapshot"
    # No filesystem traversal during ordinary search: fail if inventory is accidentally used.
    monkeypatch.setattr(
        "lct.query.inventory",
        lambda _: (_ for _ in ()).throw(AssertionError("source scan in query")),
    )
    q.search_code("weight", mode="bm25")
    with pytest.raises(ToolError, match="Injected"):
        build(c, lexical_only=True, fail_at="before_publish")
    assert current(c) == second["version"]
    assert Query(c).search_code("weight", mode="bm25")["results"]
    recover(c, first["version"])
    assert current(c) == first["version"]
    # Delete then move/rename: remove old node/posting/edge identities.
    (root / "src/new.py").unlink()
    source.rename(root / "src/moved.py")
    third = build(c, lexical_only=True)
    assert third["incremental"]["nodes_removed"] > 0
    with Query(c).db(Path(c["data"]) / "versions" / third["version"]) as db:
        assert not db.execute(
            "select 1 from nodes where path in ('src/new.py','src/sample.py')"
        ).fetchone()
        assert not db.execute(
            "select 1 from postings p left join nodes n using(node_id) where n.node_id is null"
        ).fetchone()
    # Retire first snapshot with sufficient updates; old cursor must fail, never silently switch.
    build(c, lexical_only=True)
    build(c, lexical_only=True)
    with pytest.raises(ToolError, match="expired"):
        q.search_code("weight", mode="bm25", candidates=10, limit=1, cursor=cursor)


def test_program_format_freshness_and_missing(sandbox):
    c, root = sandbox
    assert Query(c).index_status()["status"] == "missing_or_incompatible"
    build(c, lexical_only=True)
    q = Query(c)
    assert q.index_status(refresh=True)["freshness"]["status"] == "matched_at_check"
    (root / "src/new.py").write_text("def new(): pass\n")
    assert q.index_status(refresh=True)["freshness"]["status"] == "stale"
    folder, m = manifest(c)
    changed = dict(m, format=999)
    atomic(folder / "summary.json", changed)
    assert Query(c).index_status()["status"] == "missing_or_incompatible"
    with pytest.raises(ToolError, match="incompatible"):
        Query(c).search_code("weight", mode="bm25")
    atomic(folder / "manifest.json", m)
    changed = dict(m, program_hash="wrong")
    atomic(folder / "manifest.json", changed)
    assert Query(c).index_status()["status"] == "missing_or_incompatible"


def test_no_dense_fabrication(sandbox):
    c, _ = sandbox
    build(c, lexical_only=True)
    assert Query(c).index_status()["status"] == "ready_without_dense"
    with pytest.raises(ToolError, match="Dense index unavailable"):
        Query(c).search_code("weight", mode="dense")


def test_backup_restore_and_corruption(sandbox, tmp_path):
    c, _ = sandbox
    build(c, lexical_only=True)
    result = backup(c)
    restored = tmp_path / "restored"
    restore(c, result["archive"], restored)
    assert (restored / "uv.lock").is_file() and (restored / "lct/query.py").is_file()
    assert not (restored / ".venv").exists()
    folder, m = manifest(c)
    validate_folder(restored / "data/versions" / m["version"], m)
    with pytest.raises(ToolError, match="must not exist"):
        restore(c, result["archive"], restored)
    catalog = folder / "catalog.sqlite"
    with catalog.open("ab") as f:
        f.write(b"corrupt")
    with pytest.raises(ToolError, match="checksum"):
        validate_folder(folder, m)


def test_graph_direction_and_output_caps(sandbox):
    c, _ = sandbox
    build(c, lexical_only=True)
    q = Query(c)
    rows = q.search_code("helper", mode="bm25")["results"]
    nid = next(r["node_id"] for r in rows if r["qualname"] == "helper")
    incoming = q.get_relations([nid], ["CALLS"], "in")
    assert incoming["edges"] and all(e["target"] == nid for e in incoming["edges"])
    owners = q.get_relations([nid], ["CONTAINS"], "in")
    assert any(":module:" in e["source"] for e in owners["edges"])
    with pytest.raises(ToolError):
        q.get_relations([nid], depth=99)
    bounded = q.get_relations([nid], direction="both", max_edges=1)
    assert len(bounded["edges"]) <= 1


def test_actual_process_interruption_leaves_old_version(sandbox):
    import sys

    c, _ = sandbox
    first = build(c, lexical_only=True)
    code = """import os,sys
from lct.common import config
import lct.storage as storage
c=config(sys.argv[1])
real=storage.atomic
def crash(path,value):
    if path.name=='current.json': os._exit(17)
    return real(path,value)
storage.atomic=crash
storage.build(c,lexical_only=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, c["_path"]],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 17
    assert current(c) == first["version"]
    assert Query(c).search_code("weight", mode="bm25")["results"]
    rebuilt = build(c, lexical_only=True)
    assert rebuilt["incremental"]["nodes_updated"] == 0


def test_registration_preserves_others_and_is_idempotent(tmp_path):
    import sys
    import tomllib

    dest = tmp_path / "codex-config.toml"
    dest.write_text(
        'model="unchanged"\n[mcp_servers.other]\ncommand="other-command"\n', encoding="utf-8"
    )
    command = [sys.executable, str(ROOT / "register_mcp.py"), "--codex-config", str(dest)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    before = dest.read_bytes()
    subprocess.run(command, capture_output=True, text=True, check=True)
    assert dest.read_bytes() == before
    data = tomllib.loads(dest.read_text(encoding="utf-8"))
    assert (
        data["model"] == "unchanged" and data["mcp_servers"]["other"]["command"] == "other-command"
    )
    assert data["mcp_servers"]["agentic_trpg_local_code"]["env_vars"] == ["VOYAGE_API_KEY"]
    assert "other_settings_unchanged" in first.stdout
