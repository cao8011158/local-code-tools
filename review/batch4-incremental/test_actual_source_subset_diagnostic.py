"""Bounded real-byte source probe; never executes or edits the business checkout."""

import ast
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import lct.extract as extraction
from lct.storage import build, manifest
from tests.synthetic_support import initialize


FIXTURE = Path(__file__).with_name("fixtures") / "actual-source-subset"
SOURCE = FIXTURE / "src/trpg_state_machine"
SELECTED = ("availability.py", "errors.py", "item_units.py")
MUTATION = (b"context=context", b"context=None")
SOURCE_COMMIT = "a7b0804d5635e185a79ff3c1d1fa6241c2b858fe"


def _records(config, version):
    folder, _ = manifest(config, version)
    result = {}
    for filename, tables in (
        ("catalog.sqlite", ("nodes", "edges")),
        ("graph-sites.sqlite", ("sites", "query_observations",
                                "import_dependencies", "import_requests")),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                result[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                       for (raw,) in db.execute(f"select data from {table}"))
    return result


def test_real_byte_subset_falls_back_and_matches_full_oracle(tmp_path, monkeypatch):
    config, isolated = initialize(tmp_path / "isolated")
    (isolated / "src/weights.py").unlink()
    (isolated / "docs/guide.md").unlink()
    target = isolated / "src/trpg_state_machine"
    target.mkdir()
    provenance = {}
    source_provenance = json.loads((FIXTURE / "provenance.json").read_text())
    assert source_provenance["commit"] == SOURCE_COMMIT
    blobs = source_provenance["files"]
    for filename in SELECTED:
        source = SOURCE / filename
        raw = source.read_bytes()
        destination = target / filename
        shutil.copyfile(source, destination)
        assert destination.read_bytes() == raw
        git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert git_blob == blobs["src/trpg_state_machine/" + filename]["git_blob_sha1"]
        assert hashlib.sha256(raw).hexdigest() == blobs[
            "src/trpg_state_machine/" + filename]["sha256"]
        provenance[filename] = {"source": str(source), "sha256": hashlib.sha256(raw).hexdigest(),
                                "git_blob_sha1": git_blob, "bytes": len(raw)}
    config["repositories"][0]["name"] = "trpg-state-machine-real-byte-subset"
    parsed = []
    original = extraction.python_nodes

    def count(file):
        parsed.append(file["path"])
        return original(file)

    monkeypatch.setattr(extraction, "python_nodes", count)
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert baseline["simple_python_certificate"] is None
    old_records = _records(config, baseline["version"])
    baseline_parsed = list(parsed)
    parsed.clear()
    changed_file = target / "availability.py"
    before = changed_file.read_bytes()
    assert before.count(MUTATION[0]) == 1
    changed_file.write_bytes(before.replace(*MUTATION))
    assert ast.parse(changed_file.read_bytes())
    updated = build(config, offline=True, lexical_only=True)
    update_parsed = list(parsed)
    assert updated["incremental"]["analysis_scope"]["mode"] == "full-graph"
    assert updated["incremental"]["analysis_scope"]["reason"] == "previous-simple-python-certificate-unavailable"
    assert len(update_parsed) == len(SELECTED)
    oracle = dict(config, data=str(tmp_path / "oracle"))
    fresh = build(oracle, offline=True, lexical_only=True)
    assert _records(config, updated["version"]) == _records(oracle, fresh["version"])
    assert _records(config, baseline["version"]) == old_records
    evidence = {"sources": provenance, "source_commit": SOURCE_COMMIT,
                "mutation": {"path": "availability.py",
                "old": MUTATION[0].decode(), "new": MUTATION[1].decode()},
                "baseline_parse_calls": baseline_parsed,
                "update_parse_calls": update_parsed,
                "updated_scope": updated["incremental"]["analysis_scope"],
                "record_counts": {name: len(rows) for name, rows in old_records.items()},
                "differential_equal": True, "old_version_immutable": True}
    (Path(__file__).with_name("actual-source-subset-result.json")).write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n")
