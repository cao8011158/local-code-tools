"""Build tiny isolated indices with deterministic SYNTHETIC vectors, never provider output."""

import contextlib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

from lct.common import ROOT, ToolError, atomic, config, inventory
from lct.embedding import Embeddings, vector_key
from lct.extract import embedding_texts, extract
from lct.query import Query
from lct.storage import build

FIXTURES = Path(__file__).parent / "fixtures/synthetic"
QUERY = "weight"


def deterministic_vector(text):
    """Two deterministic basis coordinates; unit-test data with no semantic meaning."""
    h = hashlib.sha256(text.encode()).digest()
    vector = np.zeros(1024, dtype=np.float32)
    vector[int.from_bytes(h[:2], "big") % 256] = 1.0
    vector[256 + int.from_bytes(h[2:4], "big") % 256] = 0.25
    return vector / np.linalg.norm(vector)


@contextlib.contextmanager
def forbid_provider():
    """Fail closed on a cache miss during demos, including outside pytest."""
    old = Embeddings.call

    def denied(*args, **kwargs):
        raise AssertionError("SYNTHETIC test/demo cannot call Embedding API")

    Embeddings.call = denied
    try:
        yield
    finally:
        Embeddings.call = old


def initialize(destination):
    """Create an owned fixture root; never overwrite an existing directory."""
    folder = Path(destination).resolve()
    if folder.exists():
        raise ToolError("Synthetic output must not exist; choose another directory")
    repo = folder / "source"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    shutil.copyfile(FIXTURES / "source.py", repo / "src/weights.py")
    shutil.copyfile(FIXTURES / "guide.md", repo / "docs/guide.md")
    commands = [
        ["init", str(repo)],
        ["-C", str(repo), "config", "user.name", "Synthetic Tests"],
        ["-C", str(repo), "config", "user.email", "synthetic@example.invalid"],
        ["-C", str(repo), "add", "src/weights.py", "docs/guide.md"],
        ["-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-m", "synthetic fixture"],
    ]
    for args in commands:
        subprocess.run(["git", *args], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    c = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
    c["repositories"] = [dict(name="synthetic-review", path=str(repo), code_roots=["src"])]
    c["data"] = str(folder / "data")
    c["synthetic_fixture_notice"] = (
        "SYNTHETIC VECTORS ONLY; runtime model fields are format constraints, not an API provenance claim"
    )
    path = folder / "config.json"
    atomic(path, c)
    c = config(path)
    atomic(
        folder / "SYNTHETIC_TEST_ONLY.json",
        json.loads((FIXTURES / "vectors.json").read_text(encoding="utf-8-sig")),
    )
    return c, repo


def seed_cache(c):
    """Insert only synthetic inputs into this fixture's private cache; never use live data."""
    files, _, _ = inventory(c)
    nodes, _ = extract(files)
    texts = embedding_texts(nodes, files)
    target = next(t for t in texts if ":function:base_weight#" in t["node_id"])
    cache = Embeddings(c)
    keys = []
    try:
        for t in texts:
            key = vector_key(c["embedding"], t["text"], "document")
            keys.append(key)
            cache.db.execute(
                "insert or ignore into vectors values(?,?,?,?,?)",
                (
                    key,
                    "document",
                    deterministic_vector(t["text"]).tobytes(),
                    "SYNTHETIC-TEST-ONLY",
                    0,
                ),
            )
        query_vector = deterministic_vector(target["text"])
        cache.db.execute(
            "insert or ignore into vectors values(?,?,?,?,?)",
            (
                vector_key(c["embedding"], QUERY, "query"),
                "query",
                query_vector.tobytes(),
                "SYNTHETIC-TEST-ONLY",
                0,
            ),
        )
        cache.db.commit()
        assert cache.requests == 0
    finally:
        cache.close()
    return keys


def build_fixture(c):
    """Call the actual production builder, explicitly offline with preseeded synthetic data."""
    seed_cache(c)
    with forbid_provider():
        result = build(c, offline=True)
    assert result["embedding_run"]["requests"] == 0
    return result


def query_fixture(c):
    """Exercise production query methods; these checks say nothing about retrieval quality."""
    q = Query(c)
    with forbid_provider():
        results = {
            mode: q.search_code(QUERY, mode=mode, candidates=10, limit=3)
            for mode in ("bm25", "dense", "rrf")
        }
        docs = q.search_docs("重量 weight", limit=3)
    return results, docs
