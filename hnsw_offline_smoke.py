"""Offline infrastructure validation using authentic historical query embeddings.

This is not current-corpus dense retrieval acceptance and does not replace a real
Voyage build. It tests the installed HNSW implementation against exact cosine only.
"""

from pathlib import Path

import numpy as np
from usearch.index import Index

from lct.common import ROOT, atomic, config, load
from lct.embedding import vector_key


def main():
    c = config()
    legacy = Path(c["embedding"]["historical_cache"]).parent.parent
    questions = load(legacy / "questions.json")
    records = []
    for q in questions:
        for lang in ("zh", "expanded"):
            text = q[lang]
            p = Path(c["embedding"]["historical_cache"]) / (
                vector_key(c["embedding"], text, "query") + ".json"
            )
            if p.is_file():
                records.append((q["id"] + ":" + lang, np.asarray(load(p), dtype=np.float32)))
    assert len(records) >= 30
    a = np.stack([v for _, v in records])
    assert np.isfinite(a).all() and a.shape[1] == 1024
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    index = Index(ndim=1024, metric="cos", dtype="f32", **c["hnsw"])
    index.add(np.arange(len(a), dtype=np.uint64), a, threads=1)
    target = ROOT / ".tmp/historical-hnsw.usearch"
    target.parent.mkdir(exist_ok=True)
    index.save(str(target))
    restored = Index.restore(str(target), view=False)
    recalls = []
    for i, q in enumerate(a):
        exact = list(np.argsort(-(a @ q), kind="stable")[:10])
        found = [int(k) for k in restored.search(q, count=10, threads=1).keys]
        recalls.append(len(set(exact) & set(found)) / 10)
    out = dict(
        dataset="60 authentic historical query vectors, not current code corpus",
        vectors=len(a),
        metric="normalized float32 cosine",
        recall_at_10_mean=float(np.mean(recalls)),
        recall_at_10_min=float(min(recalls)),
        network_requests=0,
        current_code_dense_acceptance="See reports/current-hnsw-recall.json for actual current-corpus acceptance; this smoke covers historical query vectors only",
    )
    atomic(ROOT / "reports/hnsw-offline-smoke.json", out)
    print(out)


if __name__ == "__main__":
    main()
