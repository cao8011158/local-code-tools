"""Consistent candidate snapshots, incremental SQLite maintenance and atomic publication."""

import shutil
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import numpy as np
from usearch.index import Index

from .common import (
    FORMAT,
    SCHEMA,
    TEMPLATE,
    TOKENIZER,
    VERSION,
    ToolError,
    atomic,
    canonical,
    digest,
    identity,
    inventory,
    load,
    lock,
    now,
    program_hash,
)
from .embedding import Embeddings, bound
from .extract import embedding_texts, extract
from .graph import Graph
from .lexical import add_document

DDL = """
create table if not exists nodes(node_id text primary key, repository text, path text, kind text, data text, search_hash text);
create index if not exists node_scope on nodes(repository,kind,path);
create table if not exists files(repository text,path text,sha256 text,text text,primary key(repository,path));
create table if not exists edges(edge_id text primary key,source text,target text,kind text,status text,data text);
create index if not exists edge_source on edges(source,kind);
create index if not exists edge_target on edges(target,kind);
create table if not exists postings(term text,node_id text,tf integer,primary key(term,node_id));
create index if not exists posting_node on postings(node_id);
create table if not exists lengths(node_id text primary key,repository text,kind text,length integer);
create table if not exists terms(term text primary key,df integer);
"""


def current(c):
    """Read an atomic version pointer; an incomplete candidate is never considered current."""
    p = Path(c["data"]) / "current.json"
    return load(p)["version"] if p.exists() else None


def manifest(c, version=None, compatible=True):
    """Validate schema/config/build compatibility before allowing queries."""
    version = version or current(c)
    if not version or "/" in version or "\\" in version or ".." in version:
        raise ToolError("Index missing or invalid version")
    folder = Path(c["data"]) / "versions" / version
    if not (folder / "manifest.json").exists():
        raise ToolError("Index version expired or incomplete")
    m = load(folder / "manifest.json")
    if m.get("state") != "complete":
        raise ToolError("Index incomplete")
    if compatible and (
        m.get("schema") != SCHEMA
        or m.get("format") != FORMAT
        or m.get("template") != TEMPLATE
        or m.get("tokenizer") != TOKENIZER
        or m.get("config_hash") != identity(c)
        or m.get("program_hash") != program_hash()
    ):
        raise ToolError("Index incompatible with program/config; rebuild before querying")
    return folder, m


def validate_folder(folder, m, full=True):
    """Validate every artifact checksum and SQLite integrity before publish or restore."""
    for rel, expected in m["artifacts"].items():
        p = folder / rel
        if (
            not p.is_file()
            or (full and digest(p.read_bytes()) != expected)
            or (
                not full
                and rel in m.get("artifact_sizes", {})
                and p.stat().st_size != m["artifact_sizes"][rel]
            )
        ):
            raise ToolError("Index artifact checksum mismatch: " + rel)
    with closing(sqlite3.connect(folder / "catalog.sqlite")) as db:
        if full and db.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise ToolError("Catalog integrity check failed")
        if db.execute("select count(*) from nodes").fetchone()[0] != m["node_count"]:
            raise ToolError("Catalog node count mismatch")


def source_text(n, files):
    """Assemble lexical input from current source and existing descriptions only."""
    f = files.get((n["repository"], n["path"]))
    source = "".join(f["text"].splitlines(keepends=True)[n["start"] - 1 : n["end"]]) if f else ""
    return n["path"] + "\n" + n["qualname"] + "\n" + source


def estimate(c):
    """Extract current scope and report conservative missing-input budget, without network."""
    files, repos, fingerprint = inventory(c)
    nodes, _ = extract(files)
    texts = embedding_texts(nodes, files)
    cache = Embeddings(c)
    try:
        missing = [t["text"] for t in texts if cache.lookup(t["text"], "document") is None]
        unique = list(dict.fromkeys(missing))
        tokens = sum(bound(t) for t in unique)
        return dict(
            files=len(files),
            nodes=dict(Counter(n["kind"] for n in nodes)),
            vector_chunks=len(texts),
            uncached_unique=len(unique),
            conservative_token_byte_bound=tokens,
            list_cost_upper_usd=tokens * c["embedding"]["price_per_million_usd"] / 1e6,
            historical_cache_hits=cache.historical_hits,
            repositories=repos,
            source_fingerprint=fingerprint,
        )
    finally:
        cache.close()


def build(c, offline=False, fail_at=None, lexical_only=False):
    """Build all channels from captured source; publish only after rechecking source bytes.

    AST/Jedi relationships and HNSW are recomputed during update, not retrieval. SQLite
    nodes/edges/postings update by content difference; unchanged vectors never call API.
    """
    data = Path(c["data"])
    with lock(data / "update.lock"):
        started = time.monotonic()
        files, repos, fingerprint = inventory(c)
        nodes, asts = extract(files)
        texts = embedding_texts(nodes, files)
        edges, graph_info = Graph(nodes, asts, repos).build()
        ident = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:10]
        folder = data / "versions" / ident
        folder.mkdir(parents=True)
        atomic(folder / "build-state.json", dict(state="candidate", started=now()))
        previous = current(c)
        cache = Embeddings(c)
        try:
            vectors = (
                [] if lexical_only else cache.get_many([t["text"] for t in texts], offline=offline)
            )
            if fail_at == "after_embeddings":
                raise ToolError("Injected interruption after durable embeddings")
            old = None
            if previous:
                try:
                    old, _ = manifest(c, previous, compatible=False)
                    shutil.copy2(old / "catalog.sqlite", folder / "catalog.sqlite")
                except (OSError, ToolError):
                    old = None
            db = sqlite3.connect(folder / "catalog.sqlite")
            db.executescript(DDL)
            old_nodes = {
                r[0]: r[1:] for r in db.execute("select node_id,data,search_hash from nodes")
            }
            old_edges = {r[0]: r[1] for r in db.execute("select edge_id,data from edges")}
            new_ids = {n["node_id"] for n in nodes}
            removed = set(old_nodes) - new_ids
            for nid in removed:
                db.execute("delete from nodes where node_id=?", (nid,))
                db.execute("delete from postings where node_id=?", (nid,))
                db.execute("delete from lengths where node_id=?", (nid,))
            changed = posting_updates = 0
            byfile = {(f["repository"], f["path"]): f for f in files}
            for n in nodes:
                # Versioned node data is stored once; index_version is supplied by reader.
                f = byfile.get((n["repository"], n["path"]))
                n["file_fingerprint"] = f["sha256"] if f else None
                lexical = source_text(n, byfile)
                sh = digest(lexical)
                encoded = canonical(n)
                prior = old_nodes.get(n["node_id"])
                if not prior or prior[0] != encoded:
                    db.execute(
                        "insert or replace into nodes values(?,?,?,?,?,?)",
                        (n["node_id"], n["repository"], n["path"], n["kind"], encoded, sh),
                    )
                    changed += 1
                if not prior or prior[1] != sh:
                    add_document(db, n, lexical)
                    posting_updates += 1
            incoming = {e["edge_id"]: e for e in edges}
            for eid in set(old_edges) - set(incoming):
                db.execute("delete from edges where edge_id=?", (eid,))
            for eid, e in incoming.items():
                if eid not in old_edges:
                    db.execute(
                        "insert into edges values(?,?,?,?,?,?)",
                        (eid, e["source"], e["target"], e["kind"], e["status"], canonical(e)),
                    )
            db.execute("delete from terms")
            db.execute("insert into terms select term,count(*) from postings group by term")
            old_files = {
                (r[0], r[1]): r[2] for r in db.execute("select repository,path,sha256 from files")
            }
            for key in set(old_files) - set(byfile):
                db.execute("delete from files where repository=? and path=?", key)
            for key, f in byfile.items():
                if old_files.get(key) != f["sha256"]:
                    db.execute(
                        "insert or replace into files values(?,?,?,?)",
                        (*key, f["sha256"], f["text"]),
                    )
            db.commit()
            db.execute("vacuum")
            db.close()
            partitions = defaultdict(list)
            byid = {n["node_id"]: n for n in nodes}
            for i, t in enumerate(texts if not lexical_only else []):
                n = byid[t["node_id"]]
                partitions[n["repository"], n["kind"], n["is_test"]].append(i)
            specs = []
            for part, (key, indices) in enumerate(sorted(partitions.items())):
                a = np.asarray([vectors[i] for i in indices], dtype=np.float32)
                a /= np.linalg.norm(a, axis=1, keepdims=True)
                stem = f"partition-{part}"
                np.save(folder / (stem + ".npy"), a, allow_pickle=False)
                index = Index(
                    ndim=c["embedding"]["dimension"], metric="cos", dtype="f32", **c["hnsw"]
                )
                index.add(np.arange(len(a), dtype=np.uint64), a, threads=1)
                index.save(str(folder / (stem + ".usearch")))
                mapping = [texts[i]["node_id"] for i in indices]
                atomic(folder / (stem + ".json"), mapping)
                specs.append(
                    dict(
                        repository=key[0],
                        kind=key[1],
                        is_test=key[2],
                        stem=stem,
                        chunks=len(indices),
                        nodes=len(set(mapping)),
                    )
                )
            # Detect edits/additions/deletions during API/build, never publish a mixed snapshot.
            _, end_repos, end_fingerprint = inventory(c)
            if end_fingerprint != fingerprint or [(r["head"], r["branch"]) for r in end_repos] != [
                (r["head"], r["branch"]) for r in repos
            ]:
                raise ToolError(
                    "Sources changed during build; candidate withheld, cached vectors reusable"
                )
            m = dict(
                toolkit_version=VERSION,
                program_hash=program_hash(),
                schema=SCHEMA,
                format=FORMAT,
                template=TEMPLATE,
                tokenizer=TOKENIZER,
                config_hash=identity(c),
                embedding={k: c["embedding"][k] for k in ("model", "dimension", "dtype")},
                metric="cosine; normalized float32; exact uses dot product",
                hnsw=c["hnsw"],
                partitions=specs,
                repositories=repos,
                source_fingerprint=fingerprint,
                files=[{k: v for k, v in f.items() if k != "text"} for f in files],
                state="complete",
                dense_ready=not lexical_only,
                version=ident,
                completed=now(),
                node_count=len(nodes),
                nodes=dict(Counter(n["kind"] for n in nodes)),
                counts_by_repository={
                    r["name"]: dict(
                        Counter(n["kind"] for n in nodes if n["repository"] == r["name"])
                    )
                    for r in repos
                },
                edges=dict(Counter(e["kind"] for e in edges)),
                call_resolution=dict(Counter(e["status"] for e in edges if e["kind"] == "CALLS")),
                graph=graph_info,
                vector_chunks=0 if lexical_only else len(texts),
                planned_vector_chunks=len(texts),
                incremental=dict(
                    previous=previous,
                    nodes_updated=changed,
                    nodes_removed=len(removed),
                    postings_updated=posting_updates,
                    edges_added=len(set(incoming) - set(old_edges)),
                    edges_removed=len(set(old_edges) - set(incoming)),
                ),
                embedding_run=dict(
                    cache_hits=cache.hits,
                    historical_hits=cache.historical_hits,
                    new_vectors=cache.new_vectors,
                    requests=cache.requests,
                ),
                seconds=round(time.monotonic() - started, 2),
            )
            m["artifacts"] = {
                p.name: digest(p.read_bytes())
                for p in sorted(folder.iterdir())
                if p.name not in ("manifest.json", "build-state.json")
            }
            m["artifact_sizes"] = {rel: (folder / rel).stat().st_size for rel in m["artifacts"]}
            atomic(folder / "manifest.json", m)
            validate_folder(folder, m)
            if fail_at == "before_publish":
                raise ToolError("Injected interruption before atomic pointer publication")
            activate(c, ident)
            atomic(
                data / "freshness.json",
                dict(
                    version=ident,
                    status="matched_at_check",
                    checked_at=now(),
                    source_fingerprint=fingerprint,
                    repositories=repos,
                ),
            )
            atomic(folder / "build-state.json", dict(state="published", completed=now()))
            prune(c)
            return m
        except BaseException:
            atomic(folder / "build-state.json", dict(state="failed-or-interrupted", at=now()))
            raise
        finally:
            cache.close()


def activation_history(c):
    """Read authoritative activation order, with a conservative legacy pointer fallback."""
    path = Path(c["data"]) / "current.json"
    if not path.exists():
        return []
    pointer = load(path)
    ordered = [pointer.get("version"), pointer.get("previous")] + pointer.get("history", [])
    result = []
    for version in ordered:
        if not version or version in result:
            continue
        if not isinstance(version, str) or "/" in version or "\\" in version or ".." in version:
            raise ToolError("Invalid publication history")
        result.append(version)
    return result


def activate(c, version):
    """Atomically publish one bounded activation chain under the existing update lock.

    The pointer is the sole publication record. Completed-but-unpublished manifests
    and diagnostic build-state timestamps never participate in retention ordering.
    """
    data = Path(c["data"])
    previous = current(c)
    limit = max(2, c.get("retained_versions", 2))
    history = [version] + [v for v in activation_history(c) if v != version]
    atomic(
        data / "current.json",
        dict(version=version, previous=previous, history=history[:limit], history_schema=1),
    )


def prune(c):
    """Keep current plus recent distinct activations; never sort random version names.

    Callers hold update.lock. Legacy complete snapshots of uncertain age are preserved
    until enough explicit pointer history exists. Incomplete candidates are removed;
    completed unlisted candidates are removed once history is sufficient. Pointer-
    referenced versions survive even a stale build-state marker.
    """
    data = Path(c["data"])
    versions = data / "versions"
    history = activation_history(c)
    if not history:
        return
    limit = max(2, c.get("retained_versions", 2))
    keep = set(history[:limit])
    valid_history = []
    for version in history[:limit]:
        folder = versions / version
        if (folder / "manifest.json").is_file() and load(folder / "manifest.json").get(
            "state"
        ) == "complete":
            valid_history.append(version)
    # With insufficient legacy history, deleting an unlisted completed publication
    # could discard a required predecessor. Keep it until the chain proves enough.
    sufficient = len(valid_history) >= limit
    for folder in versions.iterdir():
        if not folder.is_dir() or folder.name in keep:
            continue
        if folder.is_symlink() or folder.resolve().parent != versions.resolve():
            raise ToolError("Unsafe version cleanup target")
        complete = (folder / "manifest.json").is_file() and load(folder / "manifest.json").get(
            "state"
        ) == "complete"
        # A legacy failed marker may have been written after pointer publication.
        # Without sufficient history, do not use that marker to discard a complete
        # snapshot whose older activation order can no longer be established.
        if not complete or sufficient:
            shutil.rmtree(folder)


def recover(c, version):
    """Explicitly validate a complete retained snapshot and atomically activate it."""
    with lock(Path(c["data"]) / "update.lock"):
        folder, m = manifest(c, version)
        validate_folder(folder, m)
        previous = current(c)
        if previous == version:
            return {"recovered": version, "previous": previous}
        activate(c, version)
        atomic(
            Path(c["data"]) / "freshness.json",
            dict(version=version, status="unchecked_after_recovery", checked_at=None),
        )
        prune(c)
        return {"recovered": version, "previous": previous}
