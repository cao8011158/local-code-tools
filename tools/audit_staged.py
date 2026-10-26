"""Audit staged source-only publication content; never print credential values."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lct.common import ROOT, load, program_hash  # noqa: E402


def main():
    """Inspect Git blobs, not just ignore rules; preserve accepted runtime bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".publication/staged-audit.json")
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    secrets = [
        v.encode()
        for k, v in os.environ.items()
        if re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", k, re.I) and len(v) > 12
    ]
    listing = []
    for path in filter(None, paths):
        assert not path.startswith(
            ("data/", "reports/", "workspaces/", ".tmp/", ".venv/", ".publication/")
        ), path
        assert not path.endswith(
            (
                ".sqlite",
                ".sqlite3",
                ".db",
                ".npy",
                ".npz",
                ".usearch",
                ".zip",
                ".tar",
                ".gz",
                ".7z",
                ".bak",
                ".pyc",
            )
        ), path
        assert path != "config.json" and not Path(path).name.startswith(".env"), path
        raw = subprocess.check_output(["git", "show", ":" + path], cwd=ROOT)
        assert len(raw) < 2 * 1024 * 1024, path
        assert all(value not in raw for value in secrets), (
            "Credential value found; value not printed"
        )
        assert not re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", raw), path
        assert not re.search(rb"(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{24,}", raw), path
        listing.append(dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    baseline = ROOT / ".publication/baseline.json"
    byte_identical = None
    if baseline.exists():
        data = load(baseline)
        for path, expected in data["core_files"].items():
            assert (
                hashlib.sha256(
                    subprocess.check_output(["git", "show", ":" + path], cwd=ROOT)
                ).hexdigest()
                == expected
            ), path
        assert program_hash() == data["program_hash"]
        byte_identical = True
    result = dict(
        files=listing,
        file_count=len(listing),
        tracked_bytes=sum(f["bytes"] for f in listing),
        accepted_runtime_byte_identical=byte_identical,
        known_environment_secrets_absent=True,
        no_database_index_cache_or_archive=True,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
