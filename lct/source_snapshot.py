"""Opt-in verified captured source input, without pretending to have a Git checkout."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .common import EXCLUDED, ToolError, digest, source_candidates

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def relative_path(value):
    """Accept only canonical, root-relative POSIX paths."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ToolError("Invalid source snapshot path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..", "") for part in value.split("/")) or path.as_posix() != value or ":" in path.parts[0]:
        raise ToolError("Invalid source snapshot path")
    return path


def local_file(root, rel):
    path = root
    for part in relative_path(rel).parts:
        path = path / part
        if path.is_symlink():
            raise ToolError("Source snapshot symlink: " + rel)
    if not path.is_file():
        raise ToolError("Source snapshot file missing: " + rel)
    return path


def inventory_snapshot(c, repo, root):
    """Verify declared membership and bytes at each explicit inventory operation."""
    manifest_name = repo["source_manifest"]
    manifest_path = local_file(root, manifest_name)
    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolError("Invalid source snapshot manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "repository", "head", "tree", "branch", "provenance", "selected_scope", "files"}:
        raise ToolError("Invalid source snapshot schema")
    if type(manifest["schema"]) is not int or manifest["schema"] != 1 or manifest["repository"] != repo["name"]:
        raise ToolError("Source snapshot schema or repository mismatch")
    if (not isinstance(manifest["head"], str) or not HEX40.fullmatch(manifest["head"])
            or not isinstance(manifest["tree"], str) or not HEX40.fullmatch(manifest["tree"])
            or manifest["branch"] != "main" or manifest["provenance"] != "github-pinned-tree"):
        raise ToolError("Invalid source snapshot provenance metadata")
    scope = {"code_roots": repo["code_roots"], "include_tests": c.get("include_tests", False),
             "exclude_files": repo.get("exclude_files", []), "docs": True,
             "root_files": [".py", ".md"], "excluded_directories": sorted(EXCLUDED)}
    if manifest["selected_scope"] != scope:
        raise ToolError("Source snapshot selected scope differs from configuration")
    if (not isinstance(scope["code_roots"], list) or not isinstance(scope["exclude_files"], list)
            or type(scope["include_tests"]) is not bool):
        raise ToolError("Invalid source snapshot scope")
    for item in scope["code_roots"] + scope["exclude_files"]:
        relative_path(item)
    for item in scope["code_roots"]:
        probe = root
        for part in PurePosixPath(item).parts:
            probe = probe / part
            if probe.is_symlink():
                raise ToolError("Source snapshot symlink scope: " + item)
    entries = manifest["files"]
    if not isinstance(entries, list):
        raise ToolError("Invalid source snapshot files")
    declared = set()
    files = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "git_blob_sha", "sha256", "bytes"}:
            raise ToolError("Invalid source snapshot file entry")
        rel = entry["path"]
        relative_path(rel)
        if rel in declared or rel == manifest_name:
            raise ToolError("Duplicate or invalid source snapshot file: " + rel)
        declared.add(rel)
        if (not isinstance(entry["git_blob_sha"], str) or not HEX40.fullmatch(entry["git_blob_sha"])
                or not isinstance(entry["sha256"], str) or not HEX64.fullmatch(entry["sha256"])
                or type(entry["bytes"]) is not int or entry["bytes"] < 0):
            raise ToolError("Invalid source snapshot file hashes: " + rel)
        p = local_file(root, rel)
        try:
            raw = p.read_bytes()
            st = p.stat()
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ToolError("Source snapshot file unreadable: " + rel) from exc
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"] or blob != entry["git_blob_sha"]:
            raise ToolError("Source snapshot bytes changed: " + rel)
        files.append({"repository": repo["name"], "path": rel, "sha256": entry["sha256"],
                      "bytes": len(raw), "mtime_ns": st.st_mtime_ns, "text": text,
                      "is_test": "tests" in PurePosixPath(rel).parts or PurePosixPath(rel).name.startswith("test_")})
    selected = {p.relative_to(root).as_posix() for p in source_candidates(c, repo, root)}
    if selected != declared:
        missing, extra = sorted(selected - declared), sorted(declared - selected)
        raise ToolError("Source snapshot membership differs: undeclared=" + repr(missing[:5])
                        + " out_of_scope=" + repr(extra[:5]))
    files.sort(key=lambda f: f["path"])
    return files, {"name": repo["name"], "path": str(root), "head": manifest["head"],
                   "tree": manifest["tree"], "branch": manifest["branch"],
                   "status": "verified captured source snapshot (not Git working tree)",
                   "source_kind": "captured_source_snapshot", "provenance": manifest["provenance"],
                   "source_manifest_sha256": digest(raw_manifest)}
