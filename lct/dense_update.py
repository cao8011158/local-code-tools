"""Write query-compatible dense partitions while reusing verified immutable artifacts.

The caller supplies already normalized float32 vectors in their final row order.
This module never requests embeddings or changes a published version. Changed
partitions are rebuilt; USearch mutation is deliberately not assumed safe.
"""

import hashlib
import io
import shutil
import stat
from pathlib import Path

import numpy as np
from usearch.index import Index

from .common import ToolError, atomic, canonical

METRIC = "cosine; normalized float32; exact uses dot product"


def _verified_bytes(folder, manifest, name):
    """Return one predecessor artifact only if it matches its recorded identity."""
    expected = manifest.get("artifacts", {}).get(name)
    if not isinstance(expected, str) or len(expected) != 64:
        return None
    path = folder / name
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if (hashlib.sha256(data).hexdigest() != expected or
            manifest.get("artifact_sizes", {}).get(name, len(data)) != len(data)):
        return None
    return data


def _previous_specs(manifest, embedding, hnsw):
    if not isinstance(manifest, dict) or not manifest.get("dense_ready") or manifest.get("state") != "complete":
        return {}
    if (manifest.get("embedding") != embedding or manifest.get("metric") != METRIC or
            manifest.get("hnsw") != hnsw):
        return {}
    result = {}
    for spec in manifest.get("partitions", []):
        if not isinstance(spec, dict):
            return {}
        key = (spec.get("repository"), spec.get("kind"), spec.get("is_test"))
        stem = spec.get("stem")
        if (key in result or not all((isinstance(key[0], str), isinstance(key[1], str),
                                      type(key[2]) is bool)) or
                not isinstance(stem, str) or not stem.startswith("partition-") or
                not stem[10:].isdigit()):
            return {}
        result[key] = spec
    return result


def write_partitions(folder, partitions, embedding, hnsw, *, prior_folder=None, prior_manifest=None):
    """Create candidate triples and specs; reuse only exact, verified old triples.

    ``partitions`` contains ``((repository, kind, is_test), array, mapping)``
    triples, in the intended ordinal order. ``mapping`` contains a node ID per
    vector row. The caller owns version publication and manifest generation.
    Returned counters distinguish reused and rebuilt partitions.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if prior_folder is not None and folder.resolve() == Path(prior_folder).resolve():
        raise ToolError("Dense candidate must differ from predecessor")
    prior = (_previous_specs(prior_manifest, embedding, hnsw)
             if prior_folder is not None else {})
    prior_folder = Path(prior_folder) if prior_folder is not None else None
    specs = []
    seen = set()
    reused = rebuilt = 0
    for part, (key, array, mapping) in enumerate(partitions):
        if (not isinstance(key, tuple) or len(key) != 3 or
                not isinstance(key[0], str) or not isinstance(key[1], str) or
                type(key[2]) is not bool or key in seen):
            raise ToolError("Invalid or duplicate dense partition key")
        seen.add(key)
        array = np.asarray(array)
        mapping = list(mapping)
        if (array.ndim != 2 or array.dtype != np.dtype("float32") or
                array.shape != (len(mapping), embedding["dimension"]) or
                not mapping or any(not isinstance(node, str) for node in mapping)):
            raise ToolError("Dense partition rows or mapping invalid")
        if not np.all(np.isfinite(array)):
            raise ToolError("Dense partition vectors must be finite")
        current_npy = io.BytesIO()
        np.save(current_npy, array, allow_pickle=False)
        current_npy = current_npy.getvalue()
        current_json = (canonical(mapping) + "\n").encode("utf-8")
        stem = f"partition-{part}"
        old = prior.get(key)
        copied = False
        if old is not None:
            old_stem = old["stem"]
            old_npy = _verified_bytes(prior_folder, prior_manifest, old_stem + ".npy")
            old_json = _verified_bytes(prior_folder, prior_manifest, old_stem + ".json")
            if (old_npy == current_npy and old_json == current_json and
                    old.get("chunks") == len(mapping) and
                    old.get("nodes") == len(set(mapping)) and
                    _verified_bytes(prior_folder, prior_manifest, old_stem + ".usearch") is not None):
                for suffix in (".npy", ".json", ".usearch"):
                    shutil.copy2(prior_folder / (old_stem + suffix), folder / (stem + suffix))
                copied = True
                reused += 1
        if not copied:
            (folder / (stem + ".npy")).write_bytes(current_npy)
            index = Index(ndim=embedding["dimension"], metric="cos", dtype="f32", **hnsw)
            index.add(np.arange(len(mapping), dtype=np.uint64), array, threads=1)
            index.save(str(folder / (stem + ".usearch")))
            atomic(folder / (stem + ".json"), mapping)
            rebuilt += 1
        specs.append(dict(repository=key[0], kind=key[1], is_test=key[2], stem=stem,
                          chunks=len(mapping), nodes=len(set(mapping))))
    return specs, dict(reused=reused, rebuilt=rebuilt)
