"""Independent public-path checks; no provider, real fixture storage and queries."""
import json
from pathlib import Path

import pytest

from lct.common import ToolError, atomic, canonical, program_hash
from lct.query import Query
from lct.storage import build, manifest, graph_detail, source_files, migrate_metadata
from tests.synthetic_support import initialize, forbid_provider


def fixture(tmp_path):
    c, _ = initialize(tmp_path / 'fixture')
    with forbid_provider():
        build(c, offline=True, lexical_only=True)
    return c


def test_public_cold_and_warm_never_read_full_evidence(tmp_path, monkeypatch):
    c = fixture(tmp_path)
    folder, m = manifest(c)
    q = Query(c)
    nid = q.search_code('weight', mode='bm25', limit=1)['results'][0]['node_id']
    reads = []
    original = Path.read_text
    def observed(path, *a, **kw):
        reads.append((path.name, path.stat().st_size))
        assert path.name not in {'manifest.json', 'source-files.json'}, str(path)
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'read_text', observed)
    for _ in range(2):
        q = Query(c)
        for __ in range(2):
            assert q.get_nodes([nid], include_source=False)['nodes']
            assert q.search_code('weight', mode='bm25', limit=1)['results']
            assert q.search_docs('weight', limit=1)['results']
            assert q.get_relations([nid], max_edges=1)['version'] == m['version']
            status = q.index_status()
            assert 'sites' not in status['graph']
            assert len(canonical(status).encode()) < 16000
    assert reads and max(size for _, size in reads) < 32000


def test_migration_preserves_legacy_bytes_and_graph(tmp_path):
    c = fixture(tmp_path)
    folder, m = manifest(c)
    full_graph = graph_detail(folder, m)
    full_files = source_files(folder, m)
    old = dict(m, graph=full_graph, files=full_files)
    for k in ('metadata_layout', 'graph_detail', 'file_count'):
        old.pop(k, None)
    original_artifacts = {k: v for k, v in m['artifacts'].items() if k.startswith('catalog') or k.startswith('partition-')}
    old['artifacts'] = original_artifacts
    old['artifact_sizes'] = {k: v for k, v in m['artifact_sizes'].items() if k in original_artifacts}
    atomic(folder / 'manifest.json', old)
    (folder / 'summary.json').unlink()
    before = (folder / 'manifest.json').read_bytes()
    with pytest.raises(ToolError, match='program hash|predecessor'):
        migrate_metadata(c, m['version'], 'f' * 64)
    with pytest.raises(ToolError, match='migrat'):
        manifest(c)
    migrate_metadata(c, m['version'], program_hash())
    assert (folder / 'manifest.json').read_bytes() == before
    _, updated = manifest(c)
    assert graph_detail(folder, updated) == full_graph
    assert source_files(folder, updated) == full_files
    assert migrate_metadata(c, m['version'], program_hash())['already_migrated']


def test_explicit_evidence_keeps_unknown_and_version(tmp_path):
    c = fixture(tmp_path)
    folder, m = manifest(c)
    expected = graph_detail(folder, m)['sites']
    q = Query(c)
    page = q.graph_evidence(offset=0, limit=1, version=m['version'])
    assert page['sites'] == expected[:1]
    assert page['version'] == m['version']
    with pytest.raises(ToolError):
        q.graph_evidence(version='nonexistent')
