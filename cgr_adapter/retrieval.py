"""Map the CGR catalog into existing LCT BM25/HNSW/RRF; never parse Python here."""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import numpy as np
from usearch.index import Index

from lct.common import (
    FORMAT,
    SCHEMA,
    TEMPLATE,
    TOKENIZER,
    VERSION,
    atomic,
    canonical,
    digest,
    identity,
    now,
    program_hash,
)
from lct.embedding import Embeddings, vector_key
from lct.extract import brief, chunks, embedding_texts, markdown_nodes, utf8_prefix
from lct.lexical import add_document
from lct.query import Query
from lct.storage import DDL, validate_folder


def synthetic_vector(text, dimension):
    """Deterministic SYNTHETIC TEST data; gives no evidence about Voyage search quality."""
    rng = np.random.default_rng(int(digest(text)[:16], 16))
    a = rng.normal(size=dimension).astype(np.float32)
    return a / np.linalg.norm(a)


class SyntheticEmbeddings(Embeddings):
    """Exercise original batching/cache, replacing only the paid transport for fixtures."""

    def call(self, texts, kind):
        import time

        arrays = [self.valid(synthetic_vector(t, self.e["dimension"])) for t in texts]
        for text, array in zip(texts, arrays):
            self.db.execute(
                "insert or replace into vectors values(?,?,?,?,?)",
                (
                    vector_key(self.e, text, kind),
                    kind,
                    array.tobytes(),
                    "SYNTHETIC-TEST-ONLY",
                    time.time(),
                ),
            )
        self.db.commit()
        self.new_vectors += len(texts)
        self.requests += 1
        return arrays


def normalize(bundle, documents):
    """Keep CGR snapshot IDs and exact source spans; DOC IDs are a separate lexical channel."""
    nodes = []
    files = []
    for source in bundle["sources"]:
        files.append(
            dict(
                repository=source["repository"],
                path=source["path"],
                text=source["text"],
                sha256=source["file_sha256"],
            )
        )
    for raw in bundle["nodes"]:
        if raw["kind"] not in {"Module", "Class", "Function"}:
            continue
        n = dict(
            raw,
            kind=raw["kind"].lower(),
            fingerprint=raw["source_sha256"],
            file_fingerprint=raw["file_sha256"],
            brief=brief(raw["docstring"]),
            is_test=any(p.startswith("test") for p in Path(raw["path"]).parts),
            graph_node_id=raw["node_id"],
        )
        # CGR source is independently checked against its captured bytes, including lambda columns.
        if digest(n["source"]) != n["fingerprint"]:
            raise ValueError("Canonical source fingerprint mismatch")
        parent = next((p for p in bundle["nodes"] if p["node_id"] == n["parent"]), None)
        if (
            parent
            and parent["kind"] != "Repository"
            and not (parent["start"] <= n["start"] <= n["end"] <= parent["end"])
        ):
            raise ValueError("Canonical ownership span mismatch")
        nodes.append(n)
    for f in documents:
        if digest(Path(f["absolute"]).read_bytes()) != f["sha256"]:
            raise ValueError("DOC changed during capture")
        files.append(f)
        for n in markdown_nodes(f):
            n["node_id"] = (
                "doc:"
                + bundle.get("retrieval_source_snapshot_id", bundle["source_snapshot_id"])
                + ":"
                + n["node_id"]
            )
            n.update(file_fingerprint=f["sha256"], graph_node_id=None)
            nodes.append(n)
    return nodes, files


def inputs(nodes, files):
    """Reuse LCT hierarchy formatting/chunking, substituting canonical exact function source."""
    result = [
        t
        for t in embedding_texts(nodes, files)
        if next(n for n in nodes if n["node_id"] == t["node_id"])["kind"] != "function"
    ]
    byid = {n["node_id"]: n for n in nodes}
    for n in nodes:
        if n["kind"] != "function":
            continue
        owner = byid.get(n["parent"], {})
        module = owner
        while module.get("kind") not in (None, "module"):
            module = byid.get(module.get("parent"), {})
        label = f"Repository: {n['repository']}\nPath: {n['path']}\nfunction: {n['qualname']}\n"
        context = utf8_prefix(
            f"Owner: {owner.get('qualname', '')}\nOwner context: {brief(owner.get('docstring'))}\nModule context: {brief(module.get('docstring'))}\n",
            2200,
        )
        for i, part in enumerate(chunks(n["source"])):
            text = label + context + part
            result.append(
                dict(
                    node_id=n["node_id"],
                    chunk=i,
                    text=text,
                    template=TEMPLATE,
                    input_hash=digest(text),
                )
            )
    return result


def build(c, bundle, documents, version):
    """Rebuild derived BM25 and HNSW from new canonical nodes; reuse only verified input vectors."""
    nodes, files = normalize(bundle, documents)
    texts = inputs(nodes, files)
    folder = Path(c["data"]) / "versions" / version
    folder.mkdir(parents=True, exist_ok=False)
    # Partition cache by all embedding configuration and test provenance, in addition to original exact text keys.
    cache_config = dict(
        c,
        data=str(
            Path(c["data"]) / "cache" / digest(canonical([c["embedding"], c["synthetic_fixture"]]))
        ),
    )
    cache = (SyntheticEmbeddings if c["synthetic_fixture"] else Embeddings)(cache_config)
    try:
        vectors = cache.get_many([t["text"] for t in texts], offline=not c["synthetic_fixture"])
        with closing(sqlite3.connect(folder / "catalog.sqlite")) as db:
            db.executescript(DDL)
            for n in nodes:
                lexical = (
                    n["path"]
                    + "\n"
                    + n["qualname"]
                    + "\n"
                    + n.get("source", n.get("docstring", ""))
                )
                db.execute(
                    "insert into nodes values(?,?,?,?,?,?)",
                    (
                        n["node_id"],
                        n["repository"],
                        n["path"],
                        n["kind"],
                        canonical(n),
                        digest(lexical),
                    ),
                )
                add_document(db, n, lexical)
            for f in files:
                db.execute(
                    "insert into files values(?,?,?,?)",
                    (f["repository"], f["path"], f["sha256"], f["text"]),
                )
            db.execute("insert into terms select term,count(*) from postings group by term")
            db.commit()
        partitions = defaultdict(list)
        byid = {n["node_id"]: n for n in nodes}
        for i, t in enumerate(texts):
            n = byid[t["node_id"]]
            partitions[n["repository"], n["kind"], n["is_test"]].append(i)
        specs = []
        for part, (key, indices) in enumerate(sorted(partitions.items())):
            a = np.asarray([vectors[i] for i in indices], dtype=np.float32)
            a /= np.linalg.norm(a, axis=1, keepdims=True)
            stem = f"partition-{part}"
            np.save(folder / (stem + ".npy"), a, allow_pickle=False)
            index = Index(ndim=c["embedding"]["dimension"], metric="cos", dtype="f32", **c["hnsw"])
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
        m = dict(
            toolkit_version=VERSION,
            program_hash=program_hash(),
            schema=SCHEMA,
            format=FORMAT,
            template=TEMPLATE,
            tokenizer=TOKENIZER,
            config_hash=identity(c),
            embedding={k: c["embedding"][k] for k in ("model", "dimension", "dtype")},
            hnsw=c["hnsw"],
            partitions=specs,
            repositories=bundle["repositories"],
            source_fingerprint=bundle.get(
                "retrieval_source_snapshot_id", bundle["source_snapshot_id"]
            ),
            graph_snapshot=bundle["snapshot_id"],
            state="complete",
            dense_ready=True,
            version=version,
            completed=now(),
            node_count=len(nodes),
            nodes=dict(Counter(n["kind"] for n in nodes)),
            counts_by_repository={
                r["name"]: dict(Counter(n["kind"] for n in nodes if n["repository"] == r["name"]))
                for r in bundle["repositories"]
            },
            edges=dict(Counter(e["kind"] for e in bundle["edges"])),
            call_resolution={"candidate": sum(e["kind"] == "CALLS" for e in bundle["edges"])},
            graph=dict(
                api_version=bundle["api_version"], parser=bundle["upstream_parser_fingerprint"]
            ),
            vector_chunks=len(texts),
            incremental=bundle["changes"],
            embedding_run=dict(
                cache_hits=cache.hits, new_vectors=cache.new_vectors, requests=cache.requests
            ),
            synthetic_fixture=c["synthetic_fixture"],
            inputs=[
                {k: t[k] for k in ("node_id", "chunk", "template", "input_hash")} for t in texts
            ],
        )
        m["artifacts"] = {p.name: digest(p.read_bytes()) for p in folder.iterdir()}
        m["artifact_sizes"] = {rel: (folder / rel).stat().st_size for rel in m["artifacts"]}
        atomic(folder / "manifest.json", m)
        validate_folder(folder, m)
        return m
    finally:
        cache.close()


class CanonicalQuery(Query):
    """Use existing ranking/filter/cursors, exact CGR spans for get_nodes and fixture-only dense transport."""

    def search(self, *args, **kwargs):
        # Original Query resolves its transport as a module global. Serialize this swap with the publication lock.
        import lct.query as core

        original = core.Embeddings
        if self.c["synthetic_fixture"]:
            c = dict(
                self.c,
                data=str(
                    Path(self.c["data"]) / "cache" / digest(canonical([self.c["embedding"], True]))
                ),
            )
            core.Embeddings = lambda ignored: SyntheticEmbeddings(c)
        try:
            return super().search(*args, **kwargs)
        finally:
            core.Embeddings = original

    def get_nodes(self, node_ids, include_source=True, version=None, max_bytes=64000):
        result = super().get_nodes(node_ids, False, version, max_bytes)
        if include_source:
            folder, _ = self.snapshot(version)
            with self.db(folder) as db:
                for row in result["nodes"]:
                    if "error" in row:
                        continue
                    n = json.loads(
                        db.execute(
                            "select data from nodes where node_id=?", (row["node_id"],)
                        ).fetchone()[0]
                    )
                    raw = n.get("source", n.get("docstring", "")).encode()
                    row["source"] = raw[: max(0, max_bytes)].decode(errors="ignore")
                    row["source_truncated"] = len(raw) > max_bytes
                    row["graph_node_id"] = n.get("graph_node_id")
                    row["column"] = n.get("column")
                    row["end_column"] = n.get("end_column")
                    max_bytes = max(0, max_bytes - len(row["source"].encode()))
        return result
