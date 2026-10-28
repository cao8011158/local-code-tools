"""Shared serialization, version identities, locking and explicit source inventory."""

import contextlib
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

VERSION = "1.0.0"
SCHEMA = 1
FORMAT = 1
TEMPLATE = "source-docstring-v1"
TOKENIZER = "camel-snake-latin-han-uni-bi-v1"
ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".worktrees",
    ".test-tmp",
    ".evaluation-worktree",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    ".pytest_cache",
    ".ruff_cache",
    "experiments",
    "generated",
    "vendor",
    "third_party",
}


class ToolError(Exception):
    """A user-visible bounded error, with no credential or provider response text."""


def digest(value):
    """Hash bytes or UTF-8 text without normalizing source content."""
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def canonical(value):
    """Stable serialization for identities and cursor condition binding."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load(path):
    """Read UTF-8 JSON, accepting a Windows UTF-8 BOM."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic(path, value):
    """Flush a same-directory temporary file then atomically replace the destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def git(root, *args):
    """Run Git metadata commands only; never import or execute indexed project code."""
    p = subprocess.run(
        ["git", "--no-pager", "-C", str(root), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    if p.returncode:
        raise ToolError("Git metadata unavailable: " + str(root))
    return p.stdout.strip()


def config(path=None):
    """Resolve runtime paths and check hard model/spending constraints."""
    path = Path(path or os.environ.get("LCT_CONFIG", ROOT / "config.json")).resolve()
    c = load(path)
    c["_path"] = str(path)
    c["data"] = str((path.parent / c.get("data", "data")).resolve())
    if c["embedding"]["model"] != "voyage-code-4" or c["embedding"]["dimension"] != 1024:
        raise ToolError("Explicit model migration required")
    e = c["embedding"]
    if e["max_requests"] > 400 or e["max_estimated_tokens"] > 15000000 or e["max_cost_usd"] > 2:
        raise ToolError("Configured limits exceed inherited ceilings")
    if e["endpoint"] != "https://api.voyageai.com/v1/embeddings":
        raise ToolError("Unapproved embedding endpoint")
    return c


def identity(c):
    """Index compatibility includes algorithm configuration and working-directory identity."""
    return digest(canonical({k: v for k, v in c.items() if not k.startswith("_")}))


def program_hash():
    """Fingerprint executable source and dependency lock, not generated data."""
    paths = sorted((ROOT / "lct").glob("*.py")) + [
        ROOT / "uv.lock",
        ROOT / "pyproject.toml",
        ROOT / "local_code_tools.py",
        ROOT / "register_mcp.py",
    ]
    return digest(canonical([(p.name, digest(p.read_bytes())) for p in paths if p.exists()]))


@contextlib.contextmanager
def lock(path):
    """OS-released advisory lock: process death needs no unsafe stale-lock deletion."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ToolError("Concurrent writer/recovery/backup is active") from None
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def inventory(c):
    """Hash current on-disk included files, including untracked additions and dirty bytes."""
    files, repos = [], []
    for repo in c["repositories"]:
        root = Path(repo["path"]).resolve()
        if "source_manifest" in repo:
            from .source_snapshot import inventory_snapshot

            snapshot_files, snapshot_repo = inventory_snapshot(c, repo, root)
            files.extend(snapshot_files)
            repos.append(snapshot_repo)
            continue
        candidates = source_candidates(c, repo, root)
        for p in sorted(candidates):
            rel = p.relative_to(root).as_posix()
            raw = p.read_bytes()
            st = p.stat()
            files.append(
                {
                    "repository": repo["name"],
                    "path": rel,
                    "sha256": digest(raw),
                    "bytes": len(raw),
                    "mtime_ns": st.st_mtime_ns,
                    "text": raw.decode("utf-8-sig"),
                    "is_test": "tests" in p.relative_to(root).parts or p.name.startswith("test_"),
                }
            )
        repos.append(
            {
                "name": repo["name"],
                "path": str(root),
                "head": git(root, "rev-parse", "HEAD"),
                "branch": git(root, "branch", "--show-current"),
                "status": git(root, "status", "--short", "--branch", "--untracked-files=normal"),
            }
        )
    fingerprint = digest(canonical([(f["repository"], f["path"], f["sha256"]) for f in files]))
    return files, repos, fingerprint


def source_candidates(c, repo, root):
    """Bounded existing source selection, including eligible untracked additions."""
    root = Path(root)
    try:
        starts = [root / x for x in repo["code_roots"] + ["docs"]]
        if c.get("include_tests", False):
            starts += [root / "tests"]
            starts += list((root / "packages").glob("*/tests"))
            starts += list((root / "apps").glob("*/tests"))
        candidates = {p for p in root.iterdir() if p.is_file() and p.suffix in (".md", ".py")}
        for start in starts:
            if not start.is_dir() or start.is_symlink():
                continue
            for parent, dirs, names in os.walk(start):
                dirs[:] = sorted(
                    d for d in dirs if d not in EXCLUDED and not (Path(parent) / d).is_symlink()
                )
                candidates.update(Path(parent) / n for n in names if n.endswith((".py", ".md")))
        selected = set()
        for p in candidates:
            rel = p.relative_to(root).as_posix()
            if p.is_symlink() or any(part in EXCLUDED for part in p.relative_to(root).parts):
                continue
            if rel in repo.get("exclude_files", []):
                continue
            if not c.get("include_tests", False) and "tests" in p.relative_to(root).parts:
                continue
            selected.add(p)
        return selected
    except (OSError, ValueError) as exc:
        raise ToolError("Source inventory unavailable: " + str(root)) from exc


def now():
    """UTC evidence time, independent of host locale."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
