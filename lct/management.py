"""Portable backups, checksum-verified restore and bounded cache retention."""

import json
import hashlib
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

from .common import (FORMAT, ROOT, SCHEMA, TEMPLATE, TOKENIZER, ToolError, atomic,
                     canonical, digest, identity, load, lock, program_hash)
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
        # The input file may contain a relative data path. Archive its resolved
        # identity so relocation never has to guess the source working directory.
        normalized = {k: v for k, v in c.items() if not k.startswith("_")}
        for p in (data / "versions").iterdir():
            manifest_path = p / "manifest.json"
            if manifest_path.is_file():
                vm = load(manifest_path)
                if vm.get("state") != "complete":
                    continue
                validate_folder(p, vm)
                for name in (*sorted(vm["artifacts"]), "manifest.json", "build-state.json"):
                    f = p / name
                    if name == "build-state.json" and not f.is_file():
                        continue
                    entries["data/versions/" + p.name + "/" + name] = f
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
            config_bytes = canonical(normalized).encode("utf-8")
            checks = {name: digest(path.read_bytes()) for name, path in entries.items()}
            checks["config.json"] = digest(config_bytes)
            temp = archive.with_suffix(".zip.tmp")
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2) as z:
                for name, path in entries.items():
                    z.write(path, name)
                z.writestr("config.json", config_bytes)
                z.writestr(
                    "backup-manifest.json",
                    canonical(
                        {
                            "schema": 2,
                            "version": m["version"],
                            "config_hash": identity(c),
                            "program_hash": program_hash(),
                            "index_schema": SCHEMA,
                            "index_format": FORMAT,
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
            "files": len(checks),
            "bytes": archive.stat().st_size,
        }


def restore(c, archive, destination):
    """Verify and rebind a complete snapshot before publishing a new toolkit."""
    target = Path(destination).resolve()
    if target.exists():
        raise ToolError("Restore destination must not exist")
    archive = Path(archive)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if names.count("backup-manifest.json") != 1:
            raise ToolError("Backup manifest membership mismatch")
        meta = json.loads(z.read("backup-manifest.json"))
        if meta.get("schema") != 2:
            raise ToolError("Portable relocation requires a schema-2 backup; recreate the archive with the current toolkit")
        checks = meta.get("files")
        if not isinstance(checks, dict) or set(names) != set(checks) | {"backup-manifest.json"} or len(names) != len(set(names)):
            raise ToolError("Backup manifest membership mismatch")
        for info in z.infolist():
            name = info.filename
            parts = Path(name).parts
            mode = info.external_attr >> 16
            if (not name or name.startswith("/") or name.endswith("/") or
                ":" in name or "\\" in name or ".." in parts or "." in parts or
                (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or
                not (target / name).resolve().is_relative_to(target)):
                raise ToolError("Unsafe backup member path")
        for name, expected in checks.items():
            if not isinstance(expected, str) or len(expected) != 64:
                raise ToolError("Invalid backup checksum metadata")
            h = hashlib.sha256()
            with z.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != expected:
                raise ToolError("Backup checksum mismatch")
        archived = json.loads(z.read("config.json"))
        current = json.loads(z.read("data/current.json"))["version"]
    if not isinstance(archived, dict) or not Path(archived.get("data", "")).is_absolute():
        raise ToolError("Backup configuration has no resolved data location")
    original_hash = digest(canonical(archived))
    if original_hash != meta.get("config_hash") or identity(c) != original_hash:
        raise ToolError("Restore configuration differs from archived configuration")
    program_names = sorted(name for name in checks if name.startswith("lct/") and
                           name.count("/") == 1 and name.endswith(".py"))
    program_names += [name for name in ("uv.lock", "pyproject.toml", "local_code_tools.py", "register_mcp.py") if name in checks]
    captured_program = digest(canonical([(Path(name).name, checks[name]) for name in program_names]))
    if captured_program != meta.get("program_hash") or meta.get("index_schema") != SCHEMA or meta.get("index_format") != FORMAT:
        raise ToolError("Backup program or index format incompatible with this toolkit")
    rebound = dict(archived, data=str(target / "data"))
    rebound_hash = digest(canonical(rebound))
    versions = []
    manifests = {}
    prefix = "data/versions/"
    for name in checks:
        if name.startswith(prefix) and name.endswith("/manifest.json"):
            version = name[len(prefix):-len("/manifest.json")]
            if not version or "/" in version or version in manifests:
                raise ToolError("Invalid backed-up version")
            with zipfile.ZipFile(archive) as snapshot:
                raw = snapshot.read(name)
            vm = json.loads(raw)
            compatible = (vm.get("state") == "complete" and vm.get("version") == version and
                          vm.get("config_hash") == original_hash and
                          vm.get("program_hash") == captured_program and
                          vm.get("schema") == SCHEMA and vm.get("format") == FORMAT and
                          vm.get("template") == TEMPLATE and vm.get("tokenizer") == TOKENIZER and
                          vm.get("embedding") == {k: archived["embedding"][k] for k in ("model", "dimension", "dtype")} and
                          vm.get("hnsw") == archived["hnsw"])
            manifests[version] = (vm, compatible, digest(raw))
            if compatible:
                versions.append(version)
    if current != meta.get("version") or current not in versions:
        raise ToolError("Current backup version is incompatible with archived configuration/program")
    # Stage beside the target, so a failed validation cannot publish a partial restore.
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".restore-stage-") as tmp:
        stage = Path(tmp) / "toolkit"
        stage.mkdir()
        with zipfile.ZipFile(archive) as snapshot:
            for name in checks:
                p = stage / name
                p.parent.mkdir(parents=True, exist_ok=True)
                with snapshot.open(name) as source, p.open("wb") as output:
                    shutil.copyfileobj(source, output)
        for version, (vm, compatible, _) in manifests.items():
            validate_folder(stage / prefix / version, vm)
            if compatible:
                vm["config_hash"] = rebound_hash
                atomic(stage / prefix / version / "manifest.json", vm)
        atomic(stage / "config.json", rebound)
        atomic(stage / "restore-receipt.json", dict(
            archive_sha256=digest(archive.read_bytes()),
            original_config_hash=original_hash, restored_config_hash=rebound_hash,
            original_data=archived["data"], restored_data=rebound["data"],
            rebound_versions=sorted(versions),
            original_manifest_sha256={v: manifests[v][2] for v in sorted(versions)},
        ))
        if target.exists():
            raise ToolError("Restore destination must not exist")
        os.rename(stage, target)
    return {
        "restored_to": str(target),
        "version": current,
        "rebound_versions": sorted(versions),
        "receipt": str(target / "restore-receipt.json"),
        "next": "Install locked dependencies and query or register the restored toolkit",
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
