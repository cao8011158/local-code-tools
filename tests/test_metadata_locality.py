"""Metadata migration and public query reads preserve complete frozen evidence."""

from pathlib import Path

import pytest

from lct.common import ToolError, atomic, load
from lct.management import backup, restore
from lct.query import Query
from lct.storage import (GRAPH_SITES, SOURCE_FILES, build, current, graph_detail,
                         manifest, migrate_metadata, source_files)
from tests.synthetic_support import initialize


def legacy_version(c, multiplier=0):
    built = build(c, lexical_only=True)
    folder, summary = manifest(c)
    full = dict(summary)
    full["graph"] = graph_detail(folder, summary)
    full["files"] = source_files(folder, summary)
    if multiplier:
        site = full["graph"]["sites"][0]
        full["graph"]["sites"] += [dict(site, padding="x" * 4096, ordinal=i)
                                     for i in range(multiplier)]
        full["graph"]["call_sites"] = len(full["graph"]["sites"])
    full.pop("metadata_layout")
    full.pop("graph_detail")
    full.pop("file_count")
    for rel in (GRAPH_SITES, SOURCE_FILES):
        full["artifacts"].pop(rel)
        full["artifact_sizes"].pop(rel)
        (folder / rel).unlink()
    (folder / "summary.json").unlink()
    atomic(folder / "manifest.json", full)
    return folder, full


def test_migration_scales_public_reads_with_summary_not_unrelated_evidence(tmp_path, monkeypatch):
    c, _ = initialize(tmp_path / "fixture")
    folder, old = legacy_version(c, multiplier=400)
    original = (folder / "manifest.json").read_bytes()
    assert current(c) == old["version"]
    assert Query(c).index_status()["status"] == "missing_or_incompatible"
    with pytest.raises(ToolError, match="migrate-metadata"):
        backup(c)
    with pytest.raises(ToolError, match="program hash"):
        migrate_metadata(c, old["version"], "0" * 64)
    result = migrate_metadata(c, old["version"], old["program_hash"])
    assert result["summary_bytes"] < 20000
    assert (folder / "manifest.json").read_bytes() == original
    assert current(c) == old["version"]
    _, summary = manifest(c)
    assert graph_detail(folder, summary) == old["graph"]
    assert source_files(folder, summary) == old["files"]
    reads = []
    original_read = Path.read_text
    def counted(path, *args, **kwargs):
        reads.append((path.name, path.stat().st_size))
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", counted)
    for q in (Query(c), Query(c)):
        status = q.index_status()
        assert status["graph"]["sites_available"] == old["graph"]["call_sites"]
        assert len(str(status)) < 10000
        page = q.graph_evidence(offset=0, limit=1)
        assert page["next_offset"] == 1
    assert all(name not in ("manifest.json", SOURCE_FILES) for name, _ in reads)
    assert sum(size for name, size in reads if name == "summary.json") < 40000
    assert migrate_metadata(c, old["version"], old["program_hash"])["already_migrated"]


def test_migrated_evidence_backup_restore_and_retained_version(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    folder, old = legacy_version(c, multiplier=10)
    migrate_metadata(c, old["version"], old["program_hash"])
    archive = backup(c)["archive"]
    restored = restore(c, archive, tmp_path / "restored")
    rebound = load(tmp_path / "restored/config.json")
    rebound["_path"] = str(tmp_path / "restored/config.json")
    rf, rm = manifest(rebound, old["version"])
    assert graph_detail(rf, rm) == old["graph"]
    assert source_files(rf, rm) == old["files"]
    assert Query(rebound).graph_evidence(limit=1)["sites"]
    second_archive = backup(rebound)["archive"]
    restore(rebound, second_archive, tmp_path / "restored-again")
    again = load(tmp_path / "restored-again/config.json")
    again["_path"] = str(tmp_path / "restored-again/config.json")
    af, am = manifest(again, old["version"])
    assert graph_detail(af, am) == old["graph"]
