"""Run the pinned CGR refresh and expose its companion local search tools."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout

from .cgr_lexical import candidates, connect, publish, refresh_docs, require_ready, sync_entries

CGR_VERSION = "0.6.30"
CGR = Path(sys.executable).with_name("cgr.exe" if os.name == "nt" else "cgr")
HERE = Path(__file__).resolve().parent.parent


def cgr_environment(config):
    """Return the same local CGR settings for refresh, queries and official MCP."""
    return {
        "CGR_HOME": str(config.data / "cgr"),
        "SQLITE_GRAPH_PATH": str(config.data / "cgr" / "graph.sqlite"),
        "GRAPH_BACKEND": "sqlite",
        "PYTHON_FRONTEND": "jedi",
        "CGR_VECTOR_STORE_BACKEND": "qdrant",
        "QDRANT_URL": config.qdrant_url,
        "QDRANT_COLLECTION_NAME": config.collection,
        "QDRANT_DB_PATH": str(config.data / "embedding-cache"),
        "QDRANT_VECTOR_DIM": "768",
        "CGR_EMBEDDING_PROVIDER": "unixcoder",
        "CGR_SKIP_EMBEDDINGS": "false",
        "HF_HOME": str(config.model_cache),
        "HF_HUB_CACHE": str(config.model_cache / "hub"),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "XDG_CACHE_HOME": str(config.data / "cache"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "TARGET_REPO_PATH": str(config.repositories[config.code[0]].path),
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "ORCHESTRATOR_PROVIDER": "",
        "ORCHESTRATOR_MODEL": "",
        "CYPHER_PROVIDER": "",
        "CYPHER_MODEL": "",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }


def configure(config):
    """Keep graph, caches and embeddings in the local runtime."""
    if version("code-graph-rag") != CGR_VERSION:
        raise RuntimeError(f"Expected code-graph-rag {CGR_VERSION}")
    os.environ.update(cgr_environment(config))
    os.environ.pop("QDRANT_API_KEY", None)


def slot(config, project):
    """Choose the publication boundary shared by all supported entry points."""
    return "docs" if project == config.doc else "code"


def guard(config, project):
    """Fail fast while another operation uses the same indexes."""
    config.data.mkdir(parents=True, exist_ok=True)
    return FileLock(config.data / f"{slot(config, project)}.lock", timeout=0)


def database(config, project):
    """Open the appropriate code or DOC lexical database."""
    return closing(connect(config.data / f"{slot(config, project)}.sqlite"))


def bind_indexes(config):
    """Prevent a changed config from opening indexes owned by other checkouts."""
    config.data.mkdir(parents=True, exist_ok=True)
    identity = config.data / "identity.json"
    with FileLock(config.data / "identity.lock"):
        expected = config.index_identity()
        if not identity.exists():
            temp = identity.with_suffix(".tmp")
            temp.write_text(expected, encoding="utf-8")
            temp.replace(identity)
        elif identity.read_text(encoding="utf-8") != expected:
            raise ValueError(f"Index ownership differs at {config.data}; choose a new index_dir")


def project_filter(config, projects):
    """Restrict Qdrant server-side to CGR's project payload."""
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(
                key="project",
                match=models.MatchAny(any=[config.repositories[p].name for p in projects]),
            )
        ]
    )


def graph_inventory(config, project):
    """Read the pinned CGR SQLite callable inventory in one batch."""
    graph = config.data / "cgr" / "graph.sqlite"
    sql = """
        SELECT n.id, n.label, n.key, json_extract(n.props,'$.name'),
               json_extract(n.props,'$.docstring'), COALESCE(
                   (SELECT json_extract(m.props,'$.path') FROM cgr_edges e
                    JOIN cgr_nodes m ON m.id=e.src AND m.label='Module'
                    WHERE e.dst=n.id AND e.type='DEFINES' LIMIT 1),
                   (SELECT json_extract(m.props,'$.path') FROM cgr_edges e
                    JOIN cgr_edges parent ON parent.dst=e.src AND parent.type='DEFINES'
                    JOIN cgr_nodes m ON m.id=parent.src AND m.label='Module'
                    WHERE e.dst=n.id AND e.type='DEFINES_METHOD' LIMIT 1),
                   json_extract(n.props,'$.path')
               ),
               json_extract(n.props,'$.start_line'), json_extract(n.props,'$.end_line')
        FROM cgr_nodes n
        WHERE n.label IN ('Function','Method') AND n.key>=? AND n.key<?
    """
    slug = config.repositories[project].name
    with closing(sqlite3.connect(graph.as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute(sql, (slug + ".", slug + "/")).fetchall()
    records = {}
    for node_id, kind, qualified_name, name, docstring, path, start, end in rows:
        key = json.dumps([kind, qualified_name])
        file = str(config.repositories[project].path / path) if path else None
        records[key] = (
            node_id,
            file or "",
            f"{name or qualified_name}\n{docstring or ''}",
            {
                "project": project,
                "graph_project": slug,
                "qualified_name": qualified_name,
                "node_type": kind,
                "file": file,
                "start_line": start,
                "end_line": end,
            },
        )
    return records


def qdrant():
    """Use CGR's configured Qdrant client and collection."""
    from codebase_rag.vector_store import get_qdrant_client

    return get_qdrant_client()


def verify_vectors(config, project, records):
    """Require an exact mapping between CGR's graph nodes and stored points."""
    from codebase_rag.checkout_state import state_dir
    from codebase_rag.graph_updater import _embeddings_marker
    from codebase_rag.types_defs import EmbeddingSymbol
    from codebase_rag.vector_store import embedding_point_id

    repo = config.repositories[project]
    if _embeddings_marker(state_dir(repo.path), repo.name).exists():
        raise RuntimeError("CGR reports an unfinished embedding pass; inspect the refresh log")
    expected = {
        embedding_point_id(
            config.repositories[project].name,
            EmbeddingSymbol(qualified_name=metadata["qualified_name"], label=metadata["node_type"]),
        ): (node_id, metadata["qualified_name"])
        for node_id, _, _, metadata in records.values()
    }
    client = qdrant()
    seen = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=config.collection,
            scroll_filter=project_filter(config, [project]),
            offset=offset,
            limit=512,
            with_vectors=False,
            with_payload=["node_id", "qualified_name"],
        )
        seen.update(
            (str(point.id), (point.payload.get("node_id"), point.payload.get("qualified_name")))
            for point in points
        )
        if offset is None:
            break
    if expected != seen:
        missing = expected.keys() - seen.keys()
        stale = seen.keys() - expected.keys()
        wrong = sum(seen[point] != expected[point] for point in seen.keys() & expected.keys())
        raise RuntimeError(f"{len(missing)} missing, {len(stale)} stale, {wrong} incorrect points")
    return len(seen)


def refresh_index(config, project: str) -> dict:
    """Refresh one checkout, including local changes, and publish when ready."""
    if project not in config.repositories:
        raise ValueError("project must be a configured repository alias")
    stage = "lock"
    started = time.perf_counter()
    try:
        with guard(config, project), database(config, project) as db:
            with db:
                publish(db, project, "refreshing", "refresh in progress or interrupted")
            try:
                if project == config.doc:
                    stage = "Markdown BM25"
                    with db:
                        result = refresh_docs(db, project, config.repositories[project])
                        return finish(db, project, started, result)
                stage = "CGR graph and vector sync"
                configure(config)
                log = config.data / f"{project}-refresh.log"
                command = [
                    str(CGR),
                    "start",
                    "--repo-path",
                    str(config.repositories[project].path),
                    "--project-name",
                    config.repositories[project].name,
                    "--update-graph",
                    "--no-start-stack",
                ]
                for pattern in config.repositories[project].exclude:
                    command.extend(["--exclude", pattern])
                with log.open("w", encoding="utf-8") as stream:
                    subprocess.run(
                        command,
                        cwd=HERE,
                        stdin=subprocess.DEVNULL,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                sync_seconds = time.perf_counter() - started
                stage = "graph inventory"
                records = graph_inventory(config, project)
                stage = "Qdrant verification"
                vector_start = time.perf_counter()
                count = verify_vectors(config, project, records)
                verify_seconds = time.perf_counter() - vector_start
                stage = "code BM25"
                lexical_start = time.perf_counter()
                with db:
                    changes = sync_entries(db, project, records)
                    return finish(
                        db,
                        project,
                        started,
                        {
                            "nodes": len(records),
                            "vectors": count,
                            "entry_changes": changes,
                            "cgr_seconds": round(sync_seconds, 3),
                            "verification_seconds": round(verify_seconds, 3),
                            "bm25_seconds": round(time.perf_counter() - lexical_start, 3),
                            "log": str(log),
                        },
                    )
            except Exception as error:
                result = {"project": project, "ok": False, "stage": stage, "error": str(error)}
                if project in config.code:
                    result["log"] = str(config.data / f"{project}-refresh.log")
                with db:
                    publish(db, project, "failed", result)
                return result
    except Timeout:
        return {"project": project, "ok": False, "stage": stage, "error": "index is in use"}


def finish(db, project, started, result):
    """Publish the new batch in the same transaction as the lexical updates."""
    result.update(
        project=project,
        ok=True,
        seconds=round(time.perf_counter() - started, 3),
        refreshed_at=datetime.now(timezone.utc).isoformat(),
    )
    publish(db, project, "ready", result)
    return result


def merge_rankings(vector, lexical, top_k):
    """Select unique vector slots, exclusive BM25 slots, then fill any shortage."""
    vector = list(dict.fromkeys(vector))
    lexical = list(dict.fromkeys(lexical))
    lexical_slots = top_k // 5
    result = dict.fromkeys(vector[: top_k - lexical_slots], "vector")
    for key in lexical:
        if lexical_slots == 0:
            break
        if key not in result:
            result[key] = "bm25"
            lexical_slots -= 1
    for channel, ranking in (("vector", vector), ("bm25", lexical)):
        for key in ranking:
            if len(result) == top_k:
                break
            result.setdefault(key, channel)
    vector_set, lexical_set = set(vector), set(lexical)
    return [
        (
            key,
            slot,
            [
                channel
                for channel, match in (
                    ("vector", key in vector_set),
                    ("bm25", key in lexical_set),
                )
                if match
            ],
        )
        for key, slot in result.items()
    ]


def validate_query(query, top_k):
    """Bound MCP request work and require a meaningful result limit."""
    if not query.strip() or len(query) > 2048:
        raise ValueError("query must contain 1 to 2048 characters")
    if top_k < 1 or top_k > 100:
        raise ValueError("top_k must be between 1 and 100")


def hybrid_search(config, query: str, top_k: int = 5, project: str | None = None) -> list[dict]:
    """Find code candidates, then use their qualified_name in the official graph MCP."""
    validate_query(query, top_k)
    projects = config.code if project is None else (project,)
    if not all(p in config.code for p in projects):
        raise ValueError("project must be a configured code alias")
    configure(config)
    from codebase_rag.embedder import _unixcoder_embed_code

    try:
        with guard(config, config.code[0]), database(config, config.code[0]) as db:
            require_ready(db, projects)
            lexical = candidates(db, query, top_k, projects)
            rows = {(r["project"], r["node_id"]): json.loads(r["metadata"]) for r in lexical}
            points = (
                qdrant()
                .query_points(
                    collection_name=config.collection,
                    query=_unixcoder_embed_code(query, None),
                    limit=top_k,
                    query_filter=project_filter(config, projects),
                    with_payload=["node_id", "project", "qualified_name"],
                )
                .points
            )
            project_by_slug = {config.repositories[p].name: p for p in projects}
            vector_keys = []
            for point in points:
                payload = point.payload
                key = (project_by_slug[payload["project"]], payload["node_id"])
                if key not in rows:
                    row = db.execute(
                        "SELECT metadata FROM entry WHERE project=? AND node_id=?", key
                    ).fetchone()
                    if row is None:
                        raise RuntimeError(
                            f"Qdrant/BM25 batch mismatch for {key}; run refresh_index"
                        )
                    rows[key] = json.loads(row[0])
                if rows[key]["qualified_name"] != payload["qualified_name"]:
                    raise RuntimeError(
                        f"Qdrant/BM25 identity mismatch for {key}; run refresh_index"
                    )
                vector_keys.append(key)
            ranked = merge_rankings(
                vector_keys, [(r["project"], r["node_id"]) for r in lexical], top_k
            )
            return [
                dict(rows[key], slot=source, channels=channels) for key, source, channels in ranked
            ]
    except Timeout as error:
        raise RuntimeError("code index is in use; retry after refresh") from error


def search_docs(
    config,
    query: str,
    top_k: int = 5,
    category: Literal["contract", "implementation", "history", "experiment"] | None = None,
) -> list[dict]:
    """Search DOC Markdown sections with local BM25 and optional category."""
    validate_query(query, top_k)
    if config.doc is None:
        raise ValueError("This configuration has no documentation repository")
    try:
        with guard(config, config.doc), database(config, config.doc) as db:
            require_ready(db, (config.doc,))
            return [
                json.loads(row["metadata"])
                for row in candidates(db, query, top_k, (config.doc,), category)
            ]
    except Timeout as error:
        raise RuntimeError("DOC index is in use; retry after refresh") from error
