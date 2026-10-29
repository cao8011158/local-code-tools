"""Public backup/restore/query contract in a location without the original data/source."""

import copy
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from lct.common import ToolError, atomic, config, digest, load
from lct.management import backup, restore
from lct.query import Query
from lct.storage import manifest
from tests.synthetic_support import build_fixture, initialize, query_fixture


def test_copied_program_uses_relocated_dense_and_snapshot_source(tmp_path):
    c, source = initialize(tmp_path / "fixture")
    original = build_fixture(c)
    before, docs = query_fixture(c)
    old_folder, old_manifest = manifest(c)
    hashes = {p.name: digest(p.read_bytes()) for p in old_folder.iterdir()
              if p.name in old_manifest["artifacts"]}
    archive = backup(c)["archive"]
    archive_hash = digest(Path(archive).read_bytes())
    original_manifest_hash = digest((old_folder / "manifest.json").read_bytes())
    target = tmp_path / "portable"
    result = restore(c, archive, target)
    source.rename(tmp_path / "source-gone")
    Path(c["data"]).rename(tmp_path / "data-gone")
    restored = config(target / "config.json")
    after, restored_docs = query_fixture(restored)
    assert result["version"] == original["version"]
    assert [(k, [r["node_id"] for r in v["results"]]) for k, v in before.items()] == [
        (k, [r["node_id"] for r in v["results"]]) for k, v in after.items()]
    assert docs["results"] == restored_docs["results"]
    folder, m = manifest(restored)
    assert {p.name: digest(p.read_bytes()) for p in folder.iterdir() if p.name in m["artifacts"]} == hashes
    assert (m["node_count"], m["edges"], m["call_resolution"], m["repositories"]) == (
        old_manifest["node_count"], old_manifest["edges"], old_manifest["call_resolution"], old_manifest["repositories"])
    nid = before["bm25"]["results"][0]["node_id"]
    node = Query(restored).get_nodes([nid])["nodes"][0]
    assert node["source_origin"] == "indexed_snapshot" and not node["live_file_matches"]
    env = dict(os.environ, PYTHONPATH=str(target), LCT_CONFIG=str(target / "config.json"))
    proc = subprocess.run([sys.executable, str(target / "local_code_tools.py"),
                           "search-code", "weight", "--mode", "bm25"],
                          cwd=target, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["version"] == original["version"]
    proc = subprocess.run([sys.executable, str(target / "local_code_tools.py"), "get-nodes", nid],
                          cwd=target, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["nodes"][0]["source_origin"] == "indexed_snapshot"
    receipt = load(target / "restore-receipt.json")
    assert receipt["archive_sha256"] == archive_hash
    assert receipt["original_manifest_sha256"][original["version"]] == original_manifest_hash


def test_relative_config_and_incompatible_retained_version(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    raw = load(c["_path"])
    raw["data"] = "data"
    atomic(c["_path"], raw)
    c = config(c["_path"])
    first = build_fixture(c)
    folder, m = manifest(c)
    # A retained manifest with different build identity stays incompatible.
    second_name = "incompatible-retained"
    import shutil
    shutil.copytree(folder, Path(c["data"]) / "versions" / second_name)
    other = Path(c["data"]) / "versions" / second_name / "manifest.json"
    atomic(other, dict(m, version=second_name, config_hash="f" * 64))
    atomic(other.with_name("summary.json"), dict(m, version=second_name, config_hash="f" * 64))
    archive = backup(c)["archive"]
    target = tmp_path / "portable"
    restore(c, archive, target)
    restored = config(target / "config.json")
    assert Path(restored["data"]) == target / "data"
    assert load(target / "data/versions" / second_name / "manifest.json")["config_hash"] == "f" * 64
    with pytest.raises(ToolError, match="incompatible"):
        manifest(restored, second_name)
    assert manifest(restored)[1]["version"] == first["version"]


def test_reject_mutation_corruption_legacy_and_traversal_without_publication(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    build_fixture(c)
    source = Path(backup(c)["archive"])
    altered = copy.deepcopy(c)
    altered["hnsw"]["expansion_search"] += 1
    with pytest.raises(ToolError, match="configuration"):
        restore(altered, source, tmp_path / "altered")
    for key, change in (("schema", 1), ("program_hash", "a" * 64)):
        bad = tmp_path / (key + ".zip")
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(bad, "w") as out:
            for name in original.namelist():
                raw = original.read(name)
                if name == "backup-manifest.json":
                    meta = json.loads(raw)
                    meta[key] = change
                    raw = json.dumps(meta).encode()
                out.writestr(name, raw)
        with pytest.raises(ToolError):
            restore(c, bad, tmp_path / key)
        assert not (tmp_path / key).exists()
    for kind in ("checksum", "traversal"):
        bad = tmp_path / (kind + ".zip")
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(bad, "w") as out:
            for name in original.namelist():
                raw = original.read(name)
                if kind == "checksum" and name == "config.json":
                    raw += b" "
                out.writestr(name, raw)
            if kind == "traversal":
                out.writestr("../escape", b"bad")
        with pytest.raises(ToolError):
            restore(c, bad, tmp_path / kind)
        assert not (tmp_path / kind).exists()
    # An internally checksummed archive can still contain an invalid current
    # manifest or broken SQLite. Neither may publish a destination.
    with zipfile.ZipFile(source) as original:
        all_files = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in all_files if name.startswith("data/versions/")
                         and name.endswith("/manifest.json"))
    catalog_name = manifest_name.removesuffix("manifest.json") + "catalog.sqlite"
    for kind in ("model", "artifact"):
        changed = dict(all_files)
        if kind == "model":
            m = json.loads(changed[manifest_name])
            m["embedding"]["model"] = "wrong-model"
            changed[manifest_name] = json.dumps(m).encode()
        else:
            changed[catalog_name] += b"corruption"
        meta = json.loads(changed["backup-manifest.json"])
        meta["files"] = {name: digest(raw) for name, raw in changed.items()
                         if name != "backup-manifest.json"}
        changed["backup-manifest.json"] = json.dumps(meta).encode()
        bad = tmp_path / (kind + ".zip")
        with zipfile.ZipFile(bad, "w") as out:
            for name, raw in changed.items():
                out.writestr(name, raw)
        with pytest.raises(ToolError):
            restore(c, bad, tmp_path / kind)
        assert not (tmp_path / kind).exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_text("safe")
    with pytest.raises(ToolError, match="must not exist"):
        restore(c, source, existing)
    assert sentinel.read_text() == "safe"
