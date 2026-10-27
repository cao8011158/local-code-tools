"""Shared CLI/MCP query core: bounded retrieval against one immutable index version."""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections import deque
from contextlib import closing
from pathlib import Path

import numpy as np
from usearch.index import Index

from .common import ToolError, atomic, canonical, digest, inventory, load, now
from .embedding import Embeddings
from .extract import CODE_KINDS
from .lexical import rank as lexical_rank
from .storage import current, manifest, validate_folder


class Query:
    """Cache opened partitions by version; normal queries never enumerate source files."""

    def __init__(self, c):
        self.c = c
        self.opened = {}
        self.validated = set()

    def snapshot(self, version=None):
        """Check compatibility/existence/sizes once; full checksums/integrity belong to publication."""
        folder, m = manifest(self.c, version)
        if m["version"] not in self.validated:
            validate_folder(folder, m, full=False)
            self.validated.add(m["version"])
        return folder, m

    def db(self, folder):
        """Open a catalog read-only so query failure cannot alter published data."""
        return closing(
            sqlite3.connect((folder / "catalog.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
        )

    def freshness(self, version):
        """State precisely when source matching was last checked, never assert current freshness."""
        p = Path(self.c["data"]) / "freshness.json"
        f = load(p) if p.exists() else {}
        if f.get("version") != version:
            return {"status": "retained_snapshot_not_current", "checked_at": None}
        return {
            "status": f.get("status", "unchecked"),
            "checked_at": f.get("checked_at"),
            "meaning": "Source bytes matched only at stated check time; use index_status(refresh=true) to recheck",
        }

    def index_status(self, refresh=False):
        """Explicit refresh scans included source; default status is constant-size metadata I/O."""
        try:
            folder, m = self.snapshot()
        except (ToolError, OSError, ValueError) as e:
            return {"status": "missing_or_incompatible", "error": str(e)}
        if refresh:
            _, repos, fingerprint = inventory(self.c)
            matched = fingerprint == m["source_fingerprint"] and [
                (r["head"], r["path"]) for r in repos
            ] == [(r["head"], r["path"]) for r in m["repositories"]]
            atomic(
                Path(self.c["data"]) / "freshness.json",
                dict(
                    version=m["version"],
                    status="matched_at_check" if matched else "stale",
                    checked_at=now(),
                    source_fingerprint=fingerprint,
                    repositories=repos,
                ),
            )
        return {
            "status": "ready" if m.get("dense_ready") else "ready_without_dense",
            "version": m["version"],
            "toolkit_version": m["toolkit_version"],
            "nodes": m["nodes"],
            "counts_by_repository": m["counts_by_repository"],
            "edges": m["edges"],
            "call_resolution": m["call_resolution"],
            "repositories": m["repositories"],
            "freshness": self.freshness(m["version"]),
            "embedding": m["embedding"],
            "dense_ready": m.get("dense_ready", False),
            "vector_chunks": m["vector_chunks"],
            "planned_vector_chunks": m.get("planned_vector_chunks", m["vector_chunks"]),
            "graph": m["graph"],
            "incremental": m["incremental"],
            "embedding_run": m["embedding_run"],
        }

    def conditions(self, kind, repositories, category=None, include_tests=False):
        """Filter in candidate generation, never after a small global TopK."""
        valid = {r["name"] for r in self.c["repositories"]}
        if repositories and not set(repositories) <= valid:
            raise ToolError("Unknown repository filter")
        where, params = ["n.kind=?"], [kind]
        if repositories:
            where.append("n.repository in (" + ",".join("?" for _ in repositories) + ")")
            params.extend(repositories)
        if category:
            if category not in ("contract", "implementation", "history", "experiment"):
                raise ToolError("Invalid document category")
            where.append("json_extract(n.data,'$.category')=?")
            params.append(category)
        if not include_tests:
            where.append("json_extract(n.data,'$.is_test')=0")
        return " and ".join(where), params

    def dense(
        self, folder, m, qvector, kind, repositories, count, exact=False, include_tests=False
    ):
        """Per-repository/per-level HNSW, expanding for duplicate chunks until enough nodes."""
        scores = {}
        for spec in m["partitions"]:
            if (
                spec["kind"] != kind
                or repositories
                and spec["repository"] not in repositories
                or spec.get("is_test", False)
                and not include_tests
            ):
                continue
            stem = spec["stem"]
            key = (m["version"], stem)
            if key not in self.opened:
                index = Index.restore(str(folder / (stem + ".usearch")), view=False)
                array = np.load(folder / (stem + ".npy"), allow_pickle=False)
                mapping = load(folder / (stem + ".json"))
                self.opened[key] = (index, array, mapping)
                # Memory retention is bounded across changing published versions.
                for k in list(self.opened):
                    if k[0] not in (m["version"], current(self.c)):
                        del self.opened[k]
            index, array, mapping = self.opened[key]
            if exact:
                values = np.asarray(array @ qvector).ravel()
                pairs = ((int(i), float(values[i])) for i in np.argsort(-values, kind="stable"))
                local = {}
                for idx, score in pairs:
                    local.setdefault(mapping[idx], score)
                    if len(local) >= count:
                        break
            else:
                size = min(len(mapping), max(count * 2, 16))
                while True:
                    matches = index.search(qvector, count=size, threads=1)
                    local = {}
                    for idx, distance in zip(matches.keys, matches.distances):
                        nid = mapping[int(idx)]
                        local[nid] = max(local.get(nid, -2), 1 - float(distance))
                    if len(local) >= min(count, spec["nodes"]) or size == len(mapping):
                        break
                    size = min(len(mapping), size * 2)
            for nid, score in local.items():
                scores[nid] = max(scores.get(nid, -2), score)
        # Test nodes are in distinct metadata; apply before final rank with sufficient candidate pool.
        if not include_tests and self.c.get("include_tests"):
            with self.db(folder) as db:
                excluded = {
                    r[0]
                    for r in db.execute(
                        "select node_id from nodes where json_extract(data,'$.is_test')=1"
                    )
                }
            scores = {k: v for k, v in scores.items() if k not in excluded}
        return sorted(scores, key=lambda k: (-scores[k], k))[:count]

    def compact(self, db, nid, version):
        """Return position/brief, no candidate source body or whole docstring."""
        row = db.execute("select data from nodes where node_id=?", (nid,)).fetchone()
        if not row:
            raise ToolError("Unknown node_id")
        n = json.loads(row[0])
        out = {
            k: n.get(k)
            for k in (
                "node_id",
                "repository",
                "kind",
                "qualname",
                "brief",
                "path",
                "start",
                "end",
                "is_test",
            )
        }
        out["index_version"] = version
        out["node_version"] = digest(version + ":" + nid + ":" + n["fingerprint"])
        return out

    def cursor_key(self):
        """Local HMAC integrity key is not an API credential and is safe to back up."""
        p = Path(self.c["data"]) / "cursor-key.json"
        if not p.exists():
            atomic(p, secrets.token_hex(32))
        return load(p).encode()

    def decode_cursor(self, cursor, conditions):
        try:
            raw, signature = cursor.split(".")
            expected = hmac.new(self.cursor_key(), raw.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(raw))
            if value["conditions"] != digest(canonical(conditions)):
                raise ValueError()
            if not isinstance(value["offset"], int) or value["offset"] < 0:
                raise ValueError()
            return value
        except Exception:
            raise ToolError("Invalid cursor or query conditions changed") from None

    def encode_cursor(self, version, conditions, offset):
        raw = base64.urlsafe_b64encode(
            canonical(
                dict(version=version, conditions=digest(canonical(conditions)), offset=offset)
            ).encode()
        ).decode()
        return raw + "." + hmac.new(self.cursor_key(), raw.encode(), hashlib.sha256).hexdigest()

    def search_code(
        self,
        query,
        level="function",
        repositories=None,
        mode="rrf",
        candidates=50,
        limit=10,
        cursor=None,
        exact=False,
        include_tests=False,
    ):
        """Dense/BM25/RRF; all interleaves independently ranked levels without score comparison."""
        return self.search(
            query, level, repositories, mode, candidates, limit, cursor, exact, None, include_tests
        )

    def search_docs(
        self, query, repositories=None, category=None, candidates=50, limit=10, cursor=None
    ):
        """Heading-aware DOC BM25; intentionally no paid document vectors."""
        return self.search(
            query,
            "documentsection",
            repositories,
            "bm25",
            candidates,
            limit,
            cursor,
            False,
            category,
            False,
        )

    def search(
        self,
        query,
        level,
        repositories,
        mode,
        candidates,
        limit,
        cursor,
        exact,
        category,
        include_tests,
    ):
        if level not in (*CODE_KINDS, "all", "documentsection") or mode not in (
            "dense",
            "bm25",
            "rrf",
        ):
            raise ToolError("Invalid level or retrieval mode")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ToolError("Query must contain 1-4000 characters")
        if not 1 <= candidates <= 1000 or not 1 <= limit <= 100:
            raise ToolError("Candidate cap=1000; page cap=100")
        conditions = dict(
            query=query,
            level=level,
            repositories=sorted(repositories or []),
            mode=mode,
            candidates=candidates,
            exact=exact,
            category=category,
            include_tests=include_tests,
        )
        bound_cursor = self.decode_cursor(cursor, conditions) if cursor else None
        folder, m = self.snapshot(bound_cursor["version"] if bound_cursor else None)
        version = m["version"]
        qv = None
        if mode in ("dense", "rrf"):
            if not m.get("dense_ready"):
                raise ToolError(
                    "Dense index unavailable; use bm25 or complete a real embedding build"
                )
            cache = Embeddings(self.c)
            try:
                qv = cache.get_many([query], "query")[0]
                qv = qv / np.linalg.norm(qv)
            finally:
                cache.close()
        groups = {}
        with self.db(folder) as db:
            for kind in CODE_KINDS if level == "all" else [level]:
                where, params = self.conditions(kind, repositories, category, include_tests)
                lexical = (
                    lexical_rank(db, query, where, params, candidates) if mode != "dense" else []
                )
                dense = (
                    self.dense(folder, m, qv, kind, repositories, candidates, exact, include_tests)
                    if mode != "bm25"
                    else []
                )
                br = {nid: i for i, nid in enumerate(lexical, 1)}
                dr = {nid: i for i, nid in enumerate(dense, 1)}
                if mode == "rrf":
                    pool = set(lexical) | set(dense)
                    ranked = sorted(
                        pool,
                        key=lambda nid: (
                            -sum(1 / (60 + r[nid]) for r in (br, dr) if nid in r),
                            nid,
                        ),
                    )[:candidates]
                else:
                    ranked = dense if mode == "dense" else lexical
                groups[kind] = []
                for rank, nid in enumerate(ranked, 1):
                    row = self.compact(db, nid, version)
                    row["ranks"] = {"level": rank, "dense": dr.get(nid), "bm25": br.get(nid)}
                    row["bm25_unique_in_candidates"] = (
                        nid in br and nid not in dr if mode == "rrf" else None
                    )
                    groups[kind].append(row)
        results = []
        for i in range(max((len(xs) for xs in groups.values()), default=0)):
            for rows in groups.values():
                if i < len(rows):
                    results.append(rows[i])
        offset = bound_cursor["offset"] if bound_cursor else 0
        selected = []
        size = 0
        for row in results[offset : offset + limit]:
            encoded = canonical(row)
            if selected and size + len(encoded.encode()) > 95000:
                break
            selected.append(row)
            size += len(encoded.encode())
        more = offset + len(selected) < len(results)
        return dict(
            version=version,
            freshness=self.freshness(version),
            results=selected,
            level_candidate_counts={k: len(v) for k, v in groups.items()},
            candidate_scope="bounded candidate set, not repository exhaustion",
            all_order="round-robin independently ranked levels" if level == "all" else None,
            has_more=more,
            next_cursor=self.encode_cursor(version, conditions, offset + len(selected))
            if more
            else None,
        )

    def get_nodes(self, node_ids, include_source=True, version=None, max_bytes=64000):
        """Read exact indexed source; verify file bytes before claiming live line correspondence."""
        if not 1 <= len(node_ids) <= 50 or not 1000 <= max_bytes <= 200000:
            raise ToolError("Node batch cap=50, byte cap=200000")
        folder, m = self.snapshot(version)
        repos = {r["name"]: Path(r["path"]) for r in m["repositories"]}
        results = []
        remaining = max_bytes
        with self.db(folder) as db:
            for nid in node_ids:
                row = db.execute("select data from nodes where node_id=?", (nid,)).fetchone()
                if not row:
                    results.append({"node_id": nid, "error": "not_found"})
                    continue
                n = json.loads(row[0])
                result = self.compact(db, nid, m["version"])
                result["parent"] = n["parent"]
                result["signature"] = n["signature"][:2000]
                result["content_fingerprint"] = n["fingerprint"]
                live = repos[n["repository"]] / n["path"]
                try:
                    matched = live.is_file() and digest(live.read_bytes()) == n.get(
                        "file_fingerprint"
                    )
                except OSError:
                    matched = False
                result["live_file_matches"] = matched
                result["source_origin"] = "indexed_snapshot"
                if include_source:
                    f = db.execute(
                        "select text from files where repository=? and path=?",
                        (n["repository"], n["path"]),
                    ).fetchone()
                    source = (
                        "".join(f[0].splitlines(keepends=True)[n["start"] - 1 : n["end"]])
                        if f
                        else ""
                    )
                    raw = source.encode()
                    result["source"] = raw[: max(0, remaining)].decode(errors="ignore")
                    result["source_truncated"] = len(raw) > remaining
                    remaining = max(0, remaining - len(result["source"].encode()))
                results.append(result)
        return {
            "version": m["version"],
            "freshness": self.freshness(m["version"]),
            "nodes": results,
        }

    def get_relations(
        self,
        node_ids,
        relation_types=None,
        direction="out",
        depth=1,
        max_nodes=100,
        max_edges=200,
        max_bytes=100000,
        version=None,
    ):
        """Bounded indexed adjacency traversal; unresolved/boundary edges remain visible."""
        if (
            not 1 <= len(node_ids) <= 20
            or direction not in ("in", "out", "both")
            or not 0 <= depth <= 4
            or not 1 <= max_nodes <= 500
            or not 1 <= max_edges <= 1000
            or not 1000 <= max_bytes <= 200000
        ):
            raise ToolError(
                "Invalid traversal caps/direction; depth<=4, nodes<=500, edges<=1000, bytes<=200000"
            )
        types = relation_types or ["CONTAINS", "IMPORTS", "CALLS", "INHERITS"]
        if not set(types) <= {
            "CONTAINS",
            "IMPORTS",
            "CALLS",
            "INHERITS",
            "WRAPS",
            "CONTEXT_ENTERS",
        }:
            raise ToolError("Invalid relation type")
        folder, m = self.snapshot(version)
        visited = set(node_ids)
        queue = deque((nid, 0) for nid in node_ids)
        edges = {}
        truncated = False
        size = 0
        with self.db(folder) as db:
            while queue:
                nid, d = queue.popleft()
                if d >= depth:
                    continue
                columns = (
                    ["source"]
                    if direction == "out"
                    else ["target"]
                    if direction == "in"
                    else ["source", "target"]
                )
                for column in columns:
                    sql = (
                        "select data from edges where "
                        + column
                        + "=? and kind in ("
                        + ",".join("?" for _ in types)
                        + ") order by edge_id limit ?"
                    )
                    for (raw,) in db.execute(sql, [nid, *types, max_edges + 1]):
                        e = json.loads(raw)
                        if e["edge_id"] in edges:
                            continue
                        other = e["target"] if column == "source" else e["source"]
                        if (
                            len(edges) >= max_edges
                            or size + len(raw.encode()) > max_bytes - 10000
                            or other
                            and other not in visited
                            and len(visited) >= max_nodes
                        ):
                            truncated = True
                            break
                        edges[e["edge_id"]] = e
                        size += len(raw.encode())
                        if other and other not in visited:
                            visited.add(other)
                            if not other.startswith("boundary:"):
                                queue.append((other, d + 1))
                    if truncated:
                        break
                if truncated:
                    break
        output = {
            "version": m["version"],
            "node_ids": sorted(visited),
            "edges": list(edges.values()),
            "truncated": truncated,
            "freshness": self.freshness(m["version"]),
        }
        while len(canonical(output).encode()) > max_bytes and output["edges"]:
            output["edges"].pop()
            output["truncated"] = True
            output["node_ids"] = sorted(
                set(node_ids)
                | {e[k] for e in output["edges"] for k in ("source", "target") if e[k]}
            )
        if len(canonical(output).encode()) > max_bytes:
            raise ToolError("Root node identities exceed relation output byte budget")
        return output
