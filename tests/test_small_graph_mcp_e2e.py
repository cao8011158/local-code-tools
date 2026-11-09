"""One offline SQLite build and one real SDK stdio session over fixed tiny sources."""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures/small_graph_mcp"
REPOSITORY = "small-graph-mcp"
TOOLS = {"index_status", "graph_evidence", "search_code", "search_docs", "get_nodes", "get_relations"}


def prepare(tmp_path):
    """Copy only fixed sources and prepare private Git/config/data/cache locations."""
    repo = tmp_path / "source"
    shutil.copytree(FIXTURE, repo)
    assert len(list(repo.rglob("*.py"))) == 3
    assert len(list(repo.rglob("*.md"))) == 1
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    # An allowlist, rather than os.environ.copy(), excludes provider credentials.
    env = get_default_environment()
    env.update(
        VOYAGE_API_KEY="",
        HOME=str(runtime),
        USERPROFILE=str(runtime),
        APPDATA=str(runtime),
        LOCALAPPDATA=str(runtime),
        XDG_CACHE_HOME=str(runtime),
        TMPDIR=str(runtime),
        TMP=str(runtime),
        TEMP=str(runtime),
        PYTHONDONTWRITEBYTECODE="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    template = tmp_path / "git-template"
    template.mkdir()
    for args in (
        ["init", "--template=" + str(template), str(repo)],
        ["-C", str(repo), "add", "src", "docs"],
        [
            "-C", str(repo), "-c", "user.name=Small Graph Test",
            "-c", "user.email=small-graph@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(template),
            "commit", "-m", "Fixed small graph fixture",
        ],
    ):
        subprocess.run(
            ["git", *args], env=env, cwd=tmp_path, check=True,
            capture_output=True, timeout=30,
        )
    c = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
    c["repositories"] = [dict(name=REPOSITORY, path=str(repo), code_roots=["src"])]
    c["data"] = str(tmp_path / "data")
    c["include_tests"] = False
    c["embedding"].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(c), encoding="utf-8")
    env["LCT_CONFIG"] = str(config_path)
    return repo, config_path, env


async def exercise_mcp(tmp_path, repo, config_path, env, manifest, nodes, edges):
    """Run all six acceptance groups through one initialized real MCP subprocess."""
    version = manifest["version"]
    called = set()

    def node(path, qualname):
        matches = [n for n in nodes if n["path"] == path and n["qualname"] == qualname]
        assert len(matches) == 1, (path, qualname)
        return matches[0]

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "local_code_tools.py"), "--config", str(config_path), "mcp"],
        cwd=str(tmp_path),
        env=env,
    )
    with (tmp_path / "mcp-stderr.log").open("w", encoding="utf-8") as errlog:
        # SDK context managers close the client streams and wait/terminate the child,
        # including when an assertion or bounded request timeout fails.
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=30)
            ) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "agentic-trpg-local-code"
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == TOOLS

                async def call(name, **arguments):
                    """Decode SDK tool output without bypassing the protocol or server."""
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result.content
                    called.add(name)
                    value = result.structuredContent
                    if value is None:
                        value = json.loads(next(c.text for c in result.content if c.type == "text"))
                    assert value["version"] == version
                    return value

                # 1. Service/version/counts must describe this build and catalog.
                status = await call("index_status")
                assert status["status"] == "ready_without_dense"
                assert status["toolkit_version"] == manifest["toolkit_version"]
                assert status["nodes"] == dict(Counter(n["kind"] for n in nodes))
                assert status["edges"] == dict(Counter(e["kind"] for e in edges))
                assert status["repositories"] == manifest["repositories"]
                assert not status["dense_ready"] and status["vector_chunks"] == 0
                assert status["embedding_run"]["requests"] == 0
                assert status["embedding_run"]["new_vectors"] == 0

                # 2. Explicit BM25 at each hierarchy, with exact repository/path checks.
                async def search(query, level, path, qualname):
                    """Return an expected node discovered through filtered BM25 MCP."""
                    result = await call(
                        "search_code", query=query, level=level, mode="bm25",
                        repositories=[REPOSITORY], limit=50,
                    )
                    assert result["results"]
                    assert all(
                        row["kind"] == level and row["repository"] == REPOSITORY
                        and row["index_version"] == version
                        and row["path"] in {"src/delivery.py", "src/workflow.py", "src/unknown.py"}
                        for row in result["results"]
                    )
                    expected = node(path, qualname)
                    matches = [r for r in result["results"] if r["node_id"] == expected["node_id"]]
                    assert len(matches) == 1, (query, result)
                    assert matches[0]["path"] == path and matches[0]["qualname"] == qualname
                    return matches[0]

                module = await search("workflow", "module", "src/workflow.py", "workflow")
                parcel = await search("Parcel", "class", "src/workflow.py", "Parcel")
                dispatch = await search(
                    "dispatch_parcel", "function", "src/workflow.py", "dispatch_parcel"
                )
                delivery = await search(
                    "deliver_parcel", "function", "src/delivery.py", "deliver_parcel"
                )
                method = await search("inspect", "function", "src/workflow.py", "Parcel.inspect")
                caller = await search("caller", "function", "src/unknown.py", "caller")

                # 3. Fixed Markdown heading and path, from the same version.
                docs = await call("search_docs", query="amberquartz", repositories=[REPOSITORY])
                assert len(docs["results"]) == 1
                doc = docs["results"][0]
                assert doc["node_id"] == node("docs/guide.md", "Parcel dispatch guide")["node_id"]
                assert doc["path"] == "docs/guide.md" and doc["repository"] == REPOSITORY
                assert doc["kind"] == "documentsection" and doc["index_version"] == version

                # 4. Search identities round-trip with exact snapshot bytes and line spans.
                found = [module, parcel, dispatch, delivery, method, caller, doc]
                located = await call(
                    "get_nodes", node_ids=[r["node_id"] for r in found], version=version
                )
                assert len(located["nodes"]) == len(found)
                for result, searched in zip(located["nodes"], found, strict=True):
                    expected = node(searched["path"], searched["qualname"])
                    for field in ("node_id", "qualname", "path", "repository", "start", "end"):
                        assert result[field] == expected[field]
                    lines = (repo / expected["path"]).read_text(encoding="utf-8").splitlines(True)
                    assert result["source"] == "".join(lines[expected["start"] - 1:expected["end"]])
                    assert result["index_version"] == version
                    assert result["source_origin"] == "indexed_snapshot"
                    assert result["live_file_matches"] and not result["source_truncated"]
                located_dispatch = located["nodes"][2]
                assert (located_dispatch["start"], located_dispatch["end"]) == (6, 8)
                assert "return deliver_parcel()" in located_dispatch["source"]
                # Both version-bearing APIs must fail, never fall back to current.
                for tool in ("get_nodes", "get_relations"):
                    missing = await session.call_tool(
                        tool, dict(node_ids=[dispatch["node_id"]], version="nonexistent-version")
                    )
                    assert missing.isError
                    assert "Index version expired or incomplete" in " ".join(
                        c.text for c in missing.content if c.type == "text"
                    )

                # 5. Explicit endpoint pairs in both call directions and lexical owners.
                async def relations(root, kind, direction):
                    """Fetch one bounded adjacency and compare every edge to SQLite."""
                    result = await call(
                        "get_relations", node_ids=[root], relation_types=[kind],
                        direction=direction, depth=1, version=version, max_bytes=200000,
                    )
                    assert not result["truncated"]
                    columns = ("source",) if direction == "out" else ("target",)
                    expected = [e for e in edges if e["kind"] == kind
                                and any(e[col] == root for col in columns)]
                    assert {e["edge_id"]: e for e in result["edges"]} == {
                        e["edge_id"]: e for e in expected
                    }
                    return result["edges"]

                for root, kind, direction, source, target in (
                    (dispatch["node_id"], "CALLS", "out", dispatch["node_id"], delivery["node_id"]),
                    (delivery["node_id"], "CALLS", "in", dispatch["node_id"], delivery["node_id"]),
                    (method["node_id"], "CONTAINS", "in", parcel["node_id"], method["node_id"]),
                    (parcel["node_id"], "CONTAINS", "in", module["node_id"], parcel["node_id"]),
                    (parcel["node_id"], "INHERITS", "out", parcel["node_id"],
                     node("src/delivery.py", "BaseParcel")["node_id"]),
                ):
                    actual = await relations(root, kind, direction)
                    assert {(e["source"], e["target"]) for e in actual} == {(source, target)}

                # 6. The decorator case follows Jedi's call-site signature for a.
                # Sites/reasons live in the persisted manifest, CALLS projections in SQL.
                evidence = await call("graph_evidence", offset=0, limit=500)
                sites = [s for s in evidence["sites"]
                         if s["execution_owner"] == caller["node_id"] and s["expression"] == "obj.run"]
                assert len(sites) == 1
                site = sites[0]
                assert site["unknown_origin"] is False and site["complete"] is True
                assert site["targets"] == [node("src/unknown.py", "a")["node_id"]]
                assert site["unresolved_reasons"] == []
                assert site["target_provider"] == "jedi-get-signatures"
                assert {k: v for k, v in status["graph"].items()
                        if k not in ("sites_available", "detail_tool")} == manifest["graph"]
                assert evidence["total"] == manifest["graph"]["call_sites"]
                assert evidence["next_offset"] is None
                actual = await relations(caller["node_id"], "CALLS", "out")
                partial = [e for e in actual if e.get("site_id") == site["site_id"]]
                assert {e["target"] for e in partial} == set(site["targets"])
                assert all(e["unknown_origin"] is False and e["complete"] is True
                           and e["status"] == "resolved" for e in partial)
                assert called == TOOLS
    return sorted(called)


def test_small_graph_mcp_e2e(tmp_path):
    """Build once via production CLI, then exercise all tools in one SDK session."""
    repo, config_path, env = prepare(tmp_path)
    built = subprocess.run(
        [sys.executable, str(ROOT / "local_code_tools.py"), "--config", str(config_path),
         "build", "--offline", "--lexical-only"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    (tmp_path / "build-stderr.log").write_text(built.stderr, encoding="utf-8")
    assert built.returncode == 0, built.stderr
    manifest = json.loads(built.stdout)
    data = tmp_path / "data"
    version_dir = data / "versions" / manifest["version"]
    assert list((data / "versions").iterdir()) == [version_dir]
    assert json.loads((data / "current.json").read_text())["version"] == manifest["version"]
    persisted = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == persisted
    with closing(sqlite3.connect((version_dir / "catalog.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
        nodes = [json.loads(row[0]) for row in db.execute("select data from nodes")]
        edges = [json.loads(row[0]) for row in db.execute("select data from edges")]
        files = {row[0] for row in db.execute("select path from files")}
        assert db.execute("select count(*) from postings").fetchone()[0] > 0
    assert 0 < len(nodes) <= 80 and len(nodes) == manifest["node_count"]
    assert files == {"src/delivery.py", "src/workflow.py", "src/unknown.py", "docs/guide.md"}
    assert manifest["partitions"] == [] and manifest["vector_chunks"] == 0
    with closing(sqlite3.connect((data / "vectors.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("select count(*) from vectors").fetchone()[0] == 0
    called = asyncio.run(exercise_mcp(
        tmp_path, repo, config_path, env, persisted, nodes, edges
    ))
    (tmp_path / "result.json").write_text(json.dumps(dict(
        version=manifest["version"], nodes=len(nodes), edges=len(edges), tools=called
    )), encoding="utf-8")
