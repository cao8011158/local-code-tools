"""Offline real-USearch regression for immutable dense partition reuse."""

import hashlib

import numpy as np
import pytest
from usearch.index import Index

from lct.common import ToolError, load
from lct.dense_update import METRIC, write_partitions

EMBEDDING = {"model": "synthetic", "dimension": 4, "dtype": "float"}
HNSW = {"connectivity": 8, "expansion_add": 32, "expansion_search": 32}


def matrix(*rows):
    a = np.asarray(rows, dtype=np.float32)
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def manifest(folder, specs, embedding=EMBEDDING, hnsw=HNSW):
    paths = [folder / (s["stem"] + ext) for s in specs for ext in (".npy", ".json", ".usearch")]
    return dict(state="complete", dense_ready=True, embedding=embedding, metric=METRIC,
                hnsw=hnsw, partitions=specs,
                artifacts={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                artifact_sizes={p.name: p.stat().st_size for p in paths})


def search(folder, spec, query):
    stem = spec["stem"]
    a = np.load(folder / (stem + ".npy"), allow_pickle=False)
    ids = load(folder / (stem + ".json"))
    index = Index.restore(str(folder / (stem + ".usearch")), view=False)
    found = index.search(query, count=len(ids), threads=1)
    # The returned USearch row IDs must identify the same exact stored vectors.
    assert set(map(int, found.keys)) == set(range(len(ids)))
    exact = a @ query
    assert np.allclose([1 - d for d in found.distances],
                       [exact[int(k)] for k in found.keys], atol=1e-5)
    return ids, ids[int(found.keys[0])]


def build(folder, parts, prior_folder=None, prior_manifest=None, embedding=EMBEDDING, hnsw=HNSW):
    return write_partitions(folder, parts, embedding, hnsw,
                            prior_folder=prior_folder, prior_manifest=prior_manifest)


def test_reuse_ordinal_shift_and_candidate_crash_isolation(tmp_path, monkeypatch):
    original = [(('beta', 'function', False), matrix([1, 0, 0, 0], [0, 1, 0, 0]), ['b1', 'b2']),
                (('gamma', 'function', True), matrix([0, 0, 1, 0]), ['g1'])]
    old = tmp_path / 'old'
    specs, counts = build(old, original)
    assert counts == dict(reused=0, rebuilt=2)
    m = manifest(old, specs)
    previous = {p.name: p.read_bytes() for p in old.iterdir()}
    from lct import dense_update
    real_index = dense_update.Index
    created = []

    def recording_index(*args, **kwargs):
        created.append(args)
        return real_index(*args, **kwargs)

    monkeypatch.setattr(dense_update, 'Index', recording_index)
    added = (('alpha', 'function', False), matrix([0, 0, 0, 1]), ['a1'])
    candidate = tmp_path / 'candidate'
    specs2, counts = build(candidate, [added, *original], old, m)
    assert counts == dict(reused=2, rebuilt=1) and len(created) == 1
    assert specs2[1]['stem'] == 'partition-1' and specs2[2]['stem'] == 'partition-2'
    for new, former in ((1, 0), (2, 1)):
        for ext in ('.npy', '.json', '.usearch'):
            assert (candidate / f'partition-{new}{ext}').read_bytes() == previous[f'partition-{former}{ext}']
    assert search(candidate, specs2[1], matrix([1, 0, 0, 0])[0])[1] == 'b1'
    assert search(candidate, specs2[2], matrix([0, 0, 1, 0])[0])[1] == 'g1'
    # A failed candidate does not mutate predecessor artifacts or pointer owned by caller.
    assert previous == {p.name: p.read_bytes() for p in old.iterdir()}
    with pytest.raises(ToolError, match='differ'):
        build(old, original, old, m)


def test_add_delete_update_and_ordered_mapping(tmp_path):
    key = ('repo', 'function', False)
    a = matrix([1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0])
    old = tmp_path / 'old'
    specs, _ = build(old, [(key, a, ['one', 'two', 'three'])])
    m = manifest(old, specs)
    variants = [
        (matrix([1, 0, 0, 0], [0, 0, 1, 0]), ['one', 'three'], 'three'),  # delete
        (matrix([1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]),
         ['one', 'two', 'three', 'four'], 'four'),  # add
        (matrix([1, 0, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]),
         ['one', 'two', 'three'], 'two'),  # vector update
        (a, ['three', 'two', 'one'], 'one'),  # same vector bytes, changed mapping
    ]
    for n, (vectors, ids, top) in enumerate(variants):
        folder = tmp_path / str(n)
        result, counts = build(folder, [(key, vectors, ids)], old, m)
        assert counts == dict(reused=0, rebuilt=1)
        query = vectors[ids.index(top)]
        assert search(folder, result[0], query)[1] == top


def test_corruption_and_parameter_change_rebuild_only_affected(tmp_path):
    parts = [(('a', 'module', False), matrix([1, 0, 0, 0]), ['a']),
             (('b', 'module', False), matrix([0, 1, 0, 0]), ['b'])]
    old = tmp_path / 'old'
    specs, _ = build(old, parts)
    m = manifest(old, specs)
    (old / 'partition-0.usearch').write_bytes(b'corrupted')
    result, counts = build(tmp_path / 'new', parts, old, m)
    assert counts == dict(reused=1, rebuilt=1)
    assert search(tmp_path / 'new', result[0], parts[0][1][0])[1] == 'a'
    changed_hnsw = dict(HNSW, connectivity=12)
    _, counts = build(tmp_path / 'parameter', parts, old, m, hnsw=changed_hnsw)
    assert counts == dict(reused=0, rebuilt=2)
    changed_model = dict(EMBEDDING, model='other')
    _, counts = build(tmp_path / 'model', parts, old, m, embedding=changed_model)
    assert counts == dict(reused=0, rebuilt=2)
    broken = dict(m, partitions=[m['partitions'][0], m['partitions'][0]])
    _, counts = build(tmp_path / 'ambiguous', parts, old, broken)
    assert counts == dict(reused=0, rebuilt=2)


def test_one_partition_does_not_read_unrelated_artifacts(tmp_path, monkeypatch):
    from lct import dense_update

    parts = [((f'repo-{n}', 'module', False), matrix([1, n + 1, 0, 0]), [f'node-{n}'])
             for n in range(24)]
    old = tmp_path / 'old'
    specs, _ = build(old, parts)
    m = manifest(old, specs)
    reads = []
    original = dense_update._verified_bytes

    def record(folder, manifest, name):
        reads.append(name)
        return original(folder, manifest, name)

    monkeypatch.setattr(dense_update, '_verified_bytes', record)
    target = parts[12]
    _, counts = build(tmp_path / 'one', [target], old, m)
    assert counts == dict(reused=1, rebuilt=0)
    assert set(reads) == {'partition-12.npy', 'partition-12.json', 'partition-12.usearch'}
