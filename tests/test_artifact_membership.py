"""Required version files are explicit; temporary and foreign files are not artifacts."""

import hashlib
import zipfile
from pathlib import Path

import pytest

import lct.storage as storage
from lct.common import ToolError
from lct.management import backup, restore
from tests.synthetic_support import initialize


def during_finalization(monkeypatch, c, action):
    original = storage.inventory
    calls = 0

    def wrapped(config):
        nonlocal calls
        result = original(config)
        calls += 1
        if calls == 2:
            folder = next(p for p in (Path(c["data"]) / "versions").iterdir()
                           if p.name != storage.current(c))
            action(folder)
        return result

    monkeypatch.setattr(storage, "inventory", wrapped)


def test_disappearing_incidental_file_is_not_an_artifact(tmp_path, monkeypatch):
    c, _ = initialize(tmp_path / "fixture")
    original = Path.iterdir

    def disappearing(self):
        yield from original(self)
        if self.parent == Path(c["data"]) / "versions":
            yield self / ".catalog.sqlite.temporary-gone"

    monkeypatch.setattr(Path, "iterdir", disappearing)
    m = storage.build(c, lexical_only=True)
    assert set(m["artifacts"]) == {"catalog.sqlite", "graph-sites.sqlite", "source-files.json"}
    assert storage.current(c) == m["version"]


def test_multichunk_artifact_hash_and_size_use_one_stream(tmp_path, monkeypatch):
    raw = b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"end"
    target = tmp_path / "catalog.sqlite"
    target.write_bytes(raw)
    original = Path.read_bytes

    def reject_whole_artifact_read(self):
        if self == target:
            raise AssertionError("whole-artifact read during hashing")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", reject_whole_artifact_read)
    checksum, size = storage.hash_artifact(tmp_path, "catalog.sqlite")
    assert (checksum, size) == (hashlib.sha256(raw).hexdigest(), len(raw))


def test_missing_required_artifact_withholds_candidate(tmp_path, monkeypatch):
    c, _ = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)
    during_finalization(monkeypatch, c, lambda folder: (folder / "catalog.sqlite").unlink())
    with pytest.raises(ToolError, match="artifact unavailable"):
        storage.build(c, lexical_only=True)
    assert storage.current(c) == first["version"]
    assert storage.manifest(c)[1]["version"] == first["version"]


def test_symlinked_required_artifact_withholds_candidate(tmp_path, monkeypatch):
    c, _ = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)

    def replace_with_link(folder):
        catalog = folder / "catalog.sqlite"
        catalog.rename(folder / "foreign.sqlite")
        catalog.symlink_to("foreign.sqlite")

    during_finalization(monkeypatch, c, replace_with_link)
    with pytest.raises(ToolError, match="not a regular file"):
        storage.build(c, lexical_only=True)
    assert storage.current(c) == first["version"]


@pytest.mark.parametrize("suffix", ["-journal", "-wal"])
def test_live_sqlite_sidecar_withholds_candidate(tmp_path, monkeypatch, suffix):
    c, _ = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)
    during_finalization(monkeypatch, c,
                        lambda folder: (folder / ("catalog.sqlite" + suffix)).write_bytes(b"pending"))
    with pytest.raises(ToolError, match="nonempty SQLite sidecar"):
        storage.build(c, lexical_only=True)
    assert storage.current(c) == first["version"]
    assert storage.manifest(c)[1]["version"] == first["version"]


def test_backup_excludes_foreign_files_and_restores(tmp_path):
    c, _ = initialize(tmp_path / "fixture")
    first = storage.build(c, lexical_only=True)
    folder, _ = storage.manifest(c)
    (folder / "foreign.log").write_text("not an artifact")
    archive = backup(c)["archive"]
    with zipfile.ZipFile(archive) as z:
        prefix = "data/versions/" + first["version"] + "/"
        members = {name.removeprefix(prefix) for name in z.namelist()
                   if name.startswith(prefix)}
    assert members == {"catalog.sqlite", "graph-sites.sqlite", "source-files.json",
                       "manifest.json", "summary.json", "build-state.json"}
    target = tmp_path / "restored"
    restore(c, archive, target)
    assert not (target / prefix / "foreign.log").exists()
    assert storage.validate_folder(target / prefix, storage.manifest(c)[1]) is None
