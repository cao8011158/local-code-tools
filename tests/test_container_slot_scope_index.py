"""Captured dictionary origin evidence remains scoped under unrelated growth."""

import json
import sqlite3

from lct.storage import FileDependencies, build, manifest
from tests.synthetic_support import initialize


def _rows(config, version):
    folder, metadata = manifest(config, version)
    with FileDependencies(folder, metadata) as deps:
        reads = [json.loads(data) for (data,) in deps.db.execute(
            "select data from unit_container_subscriptions")]
        writes = [json.loads(data) for (data,) in deps.db.execute(
            "select data from unit_container_writes")]
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        site = next(json.loads(raw) for (raw,) in db.execute("select data from sites")
                    if '"expression":"registry[\'go\']"' in raw)
    return site, reads, writes


def test_unrelated_local_alias_writers_do_not_change_related_source_read(tmp_path):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run():\n    return registry['go']()\n")
    evidence = []
    for count in (0, 20, 100):
        for number in range(count):
            path = repo / f"src/a_{number}.py"
            if not path.exists():
                path.write_text(f"def writer_{number}():\n"
                                "    slot={}\n    alias=slot\n    alias['x']=1\n")
        result = build(config, offline=True, lexical_only=True)
        site, reads, writes = _rows(config, result["version"])
        related = [r for r in reads if r["read_location"]["expression"] == "registry['go']"]
        assert len(related) == 1 and related[0]["key"] == "string:go"
        assert site["target_provider"] == "jedi-get-signatures"
        evidence.append((site["targets"], related[0]["origin"], len(writes)))
        if count == 0:
            identical = build(config, offline=True, lexical_only=True)
            assert identical["incremental"]["analysis_scope"]["mode"] == "identical-python-capture-reuse"
            assert _rows(config, identical["version"])[0] == site
    assert evidence[0][:2] == evidence[1][:2] == evidence[2][:2]
    assert evidence[0][2] < evidence[1][2] < evidence[2][2]


def test_only_related_imported_writers_share_receiver_origin(tmp_path):
    config, repo = initialize(tmp_path / "uncertain")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run(): return registry['go']()\n")
    sources = (
        "def parameter(registry):\n    registry['x']=1\n",
        "from b import registry\ndef imported(): registry['x']=1\n",
        "def escaped():\n    slot={}\n    slot['x']=1\n    return slot\n",
        "def called(f):\n    slot={}\n    slot['x']=1\n    f(slot)\n",
        "def rebound(registry):\n    slot={}\n    slot=registry\n    slot['x']=1\n",
        "from b import registry as remote\ndef imported_rebound():\n"
        "    slot={}\n    alias=slot\n    alias=remote\n    alias['x']=1\n",
    )
    for number, source in enumerate(sources):
        (repo / f"src/uncertain_{number}.py").write_text(source)
    built = build(config, offline=True, lexical_only=True)
    site, reads, writes = _rows(config, built["version"])
    assert site["targets"] and site["target_provider"] == "jedi-get-signatures"
    receiver = next(r["origin"] for r in reads
                    if r["read_location"]["expression"] == "registry['go']")
    related = {w["producer_location"]["path"] for w in writes if w["origin"] == receiver}
    assert "src/b.py" in related
    assert not related.intersection({f"src/uncertain_{i}.py" for i in (0, 2, 3, 4)})


def test_alias_rebound_between_fresh_local_origins_stays_isolated(tmp_path):
    config, repo = initialize(tmp_path / "aliases")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run(): return registry['go']()\n")
    (repo / "src/a.py").write_text(
        "def writer():\n    first={}\n    alias=first\n    alias['x']=1\n"
        "    second={}\n    alias=second\n    alias['x']=2\n")
    built = build(config, offline=True, lexical_only=True)
    _, reads, writes = _rows(config, built["version"])
    receiver = next(r["origin"] for r in reads
                    if r["read_location"]["expression"] == "registry['go']")
    local_origins = {w["origin"] for w in writes if w["producer_location"]["path"] == "src/a.py"}
    assert len(local_origins) == 2 and receiver not in local_origins
