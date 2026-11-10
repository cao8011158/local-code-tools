"""Portable backups, checksum-verified restore and bounded cache retention."""

import json
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

from .common import ROOT, ToolError, canonical, digest, load, lock
from .embedding import vector_key
from .storage import manifest, prune, validate_folder


def backup(c):
    """Package program/lock/config and complete indices; exclude environment/worktrees/secrets."""
    data = Path(c["data"])
    with lock(data / "update.lock"), lock(data / "embedding.lock"):
        _, m = manifest(c)
        dest = data / "backups"
        dest.mkdir(exist_ok=True)
        archive = dest / (
            "local-code-tools-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + ".zip"
        )
        entries = {}
        for name in ("lct", "tests", "reports"):
            for p in (ROOT / name).rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                    entries[p.relative_to(ROOT).as_posix()] = p
        for name in (
            "pyproject.toml",
            "uv.lock",
            "requirements.lock.txt",
            "README.md",
            "local_code_tools.py",
            "register_mcp.py",
            "protocol_acceptance.py",
            "acceptance.py",
            "dense_acceptance.py",
            "hnsw_offline_smoke.py",
            "verify_docs.py",
        ):
            p = ROOT / name
            if p.is_file():
                entries[name] = p
        entries["config.json"] = Path(c["_path"])
        for p in (data / "versions").iterdir():
            if (p / "manifest.json").is_file() and load(p / "manifest.json").get(
                "state"
            ) == "complete":
                validate_folder(p, load(p / "manifest.json"))
                for f in p.iterdir():
                    if f.is_file():
                        entries["data/versions/" + p.name + "/" + f.name] = f
        for name in ("current.json", "freshness.json", "ledger.json", "cursor-key.json"):
            if (data / name).is_file():
                entries["data/" + name] = data / name
        with tempfile.TemporaryDirectory(dir=data, prefix="backup-stage-") as tmp:
            target = Path(tmp) / "vectors.sqlite"
            with (
                closing(sqlite3.connect(data / "vectors.sqlite")) as source,
                closing(sqlite3.connect(target)) as out,
            ):
                source.backup(out)
            entries["data/vectors.sqlite"] = target
            checks = {name: digest(path.read_bytes()) for name, path in entries.items()}
            temp = archive.with_suffix(".zip.tmp")
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2) as z:
                for name, path in entries.items():
                    z.write(path, name)
                z.writestr(
                    "backup-manifest.json",
                    canonical(
                        {
                            "schema": 1,
                            "version": m["version"],
                            "files": checks,
                            "excluded": [
                                ".venv",
                                "workspaces",
                                "API credentials",
                                "Codex config backups",
                            ],
                        }
                    ),
                )
            temp.replace(archive)
        for old in sorted(dest.glob("local-code-tools-*.zip"), reverse=True)[
            max(1, c.get("retained_backups", 2)) :
        ]:
            old.unlink()
        return {
            "archive": str(archive),
            "sha256": digest(archive.read_bytes()),
            "files": len(entries),
            "bytes": archive.stat().st_size,
        }


def restore(c, archive, destination):
    """Verify before writing into a new directory, never overwrite an existing toolkit."""
    target = Path(destination).resolve()
    if target.exists():
        raise ToolError("Restore destination must not exist")
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        m = json.loads(z.read("backup-manifest.json"))
        if set(names) != set(m["files"]) | {"backup-manifest.json"} or len(names) != len(
            set(names)
        ):
            raise ToolError("Backup manifest membership mismatch")
        for name, expected in m["files"].items():
            if not (target / name).resolve().is_relative_to(target) or ":" in name or "\\" in name:
                raise ToolError("Unsafe backup member path")
            if digest(z.read(name)) != expected:
                raise ToolError("Backup checksum mismatch")
        target.mkdir(parents=True)
        z.extractall(target)
    return {
        "restored_to": str(target),
        "version": m["version"],
        "next": "uv sync --locked; configure paths; update; register_mcp.py",
    }


def gc(c):
    """Retain document vectors for complete versions plus at most 512 cached queries."""
    from .extract import embedding_texts, extract

    data = Path(c["data"])
    with lock(data / "update.lock"), lock(data / "embedding.lock"):
        prune(c)
        keep = set()
        for folder in (data / "versions").iterdir():
            if not (folder / "manifest.json").exists():
                continue
            with closing(sqlite3.connect(folder / "catalog.sqlite")) as db:
                files = [
                    dict(
                        repository=r[0],
                        path=r[1],
                        sha256=r[2],
                        text=r[3],
                        is_test="tests" in Path(r[1]).parts,
                    )
                    for r in db.execute("select repository,path,sha256,text from files")
                ]
            nodes, _ = extract(files)
            keep.update(
                vector_key(c["embedding"], t["text"], "document")
                for t in embedding_texts(nodes, files)
            )
        with closing(sqlite3.connect(data / "vectors.sqlite")) as db:
            before = db.execute("select count(*) from vectors").fetchone()[0]
            keep.update(
                r[0]
                for r in db.execute(
                    "select key from vectors where kind='query' order by used_at desc limit 512"
                )
            )
            for (key,) in db.execute("select key from vectors").fetchall():
                if key not in keep:
                    db.execute("delete from vectors where key=?", (key,))
            db.commit()
            db.execute("vacuum")
            after = db.execute("select count(*) from vectors").fetchone()[0]
        return {"vectors_before": before, "vectors_after": after, "query_cache_cap": 512}
