"""Pure, conservative planning from two already captured build inventories.

This module does not inspect a checkout, resolve a graph, or authorize reuse of
analysis results. The current analyzer has no persistent dependency closure.
"""

import sqlite3
from collections import deque
from pathlib import Path


def module_import_dependents(graph_sites, changed_modules):
    """Indexed reverse import reachability (a hint, not complete Python invalidation).

    Namespace reads include negative named lookups. Target reads include successful
    imports that resolve through a reexport to a different captured module.
    Caller/callback/Jedi dependencies are outside this index and must still fall back.
    """
    affected = set(changed_modules)
    pending = deque(sorted(affected))
    with sqlite3.connect(Path(graph_sites).resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        while pending:
            target = pending.popleft()
            sources = db.execute(
                "select source_module from import_dependencies where namespace_module=? "
                "union select d.source_module from import_dependency_targets t "
                "join import_dependencies d on d.ordinal=t.ordinal where t.target_module=?",
                (target, target),
            )
            for (source,) in sources:
                if source not in affected:
                    affected.add(source)
                    pending.append(source)
    return affected

IDENTITY_STRATEGY = "repository-wide-snapshot-id; certified-local-query-reuse"


def _files(capture):
    result = {}
    for file in capture["files"]:
        key = (file["repository"], file["path"])
        if key in result or not all(isinstance(x, str) and x for x in (*key, file["sha256"])):
            raise ValueError("Invalid or duplicate captured file identity")
        if "is_test" in file and type(file["is_test"]) is not bool:
            raise ValueError("Invalid captured is_test flag")
        result[key] = file
    return result


def _repos(capture):
    result = {}
    for repo in capture["repositories"]:
        name = repo["name"]
        if not isinstance(name, str) or not name or name in result:
            raise ValueError("Invalid or duplicate captured repository")
        if not all(isinstance(repo.get(field), str) and repo[field] for field in ("head", "branch")):
            raise ValueError("Missing captured repository head or branch")
        result[name] = repo
    return result


def plan_update(previous, current):
    """Return a JSON-serializable plan, never a certificate for partial analysis.

    Both inputs contain files (repository/path/sha256, optionally is_test),
    repositories (name/head/branch and captured provenance), config_hash,
    program_hash, and dependency_pins. The latter is a caller-captured mapping
    of dependency pin/binding metadata, including an empty mapping when known
    empty. Missing metadata fails closed rather than silently reporting no-op.
    """
    old_files, new_files = _files(previous), _files(current)
    old_repos, new_repos = _repos(previous), _repos(current)
    for capture, files, repos in ((previous, old_files, old_repos), (current, new_files, new_repos)):
        if set(r for r, _ in files) - set(repos):
            raise ValueError("Captured file has no repository metadata")
        for key in ("config_hash", "program_hash", "dependency_pins"):
            if key not in capture:
                raise ValueError("Missing captured planning metadata: " + key)
        for key in ("config_hash", "program_hash"):
            if not isinstance(capture[key], str) or not capture[key]:
                raise ValueError("Invalid captured planning metadata: " + key)
        if not isinstance(capture["dependency_pins"], dict):
            raise ValueError("Dependency pins must be a captured mapping")

    changed, removed = [], []
    affected = set()
    kinds = {"python": ("module", "class", "function"), "documentation": ("documentsection",)}

    def classify(key, file):
        repo, path = key
        category = "python" if path.endswith(".py") else "documentation" if path.endswith(".md") else "other"
        if category in kinds:
            test = bool(file.get("is_test", "tests" in path.split("/") or path.rsplit("/", 1)[-1].startswith("test_")))
            for kind in kinds[category]:
                affected.add((repo, kind, test if category == "python" else False))
        return category

    categories = set()
    for key in sorted(new_files):
        file = new_files[key]
        prior = old_files.get(key)
        metadata_changed = prior is not None and prior.get("is_test") != file.get("is_test")
        if prior is None or prior["sha256"] != file["sha256"] or metadata_changed:
            categories.add(classify(key, file))
            if prior is not None:
                categories.add(classify(key, prior))
            changed.append(dict(repository=key[0], path=key[1], change="added" if prior is None else
                                "metadata" if prior["sha256"] == file["sha256"] else "modified",
                                before=prior["sha256"] if prior else None, after=file["sha256"]))
    for key in sorted(old_files.keys() - new_files.keys()):
        file = old_files[key]
        categories.add(classify(key, file))
        removed.append(dict(repository=key[0], path=key[1], before=file["sha256"]))

    reasons = []
    if "python" in categories:
        reasons.append("python-source-changed")
    if "documentation" in categories:
        reasons.append("documentation-changed-repository-identity")
    if "other" in categories:
        reasons.append("other-captured-input-changed")
    if old_repos.keys() != new_repos.keys():
        reasons.append("repository-membership-changed")
    for name in sorted(old_repos.keys() & new_repos.keys()):
        old, new = old_repos[name], new_repos[name]
        if old.get("head") != new.get("head") or old.get("branch") != new.get("branch"):
            reasons.append("repository-revision-changed:" + name)
        # Path/status/provenance/closed-world changes can affect source mapping or
        # interpretation; only discard volatile fields explicitly identified here.
        excluded = {"name", "head", "branch"}
        if {k: v for k, v in old.items() if k not in excluded} != {k: v for k, v in new.items() if k not in excluded}:
            reasons.append("repository-metadata-changed:" + name)
    if previous["dependency_pins"] != current["dependency_pins"]:
        reasons.append("dependency-pins-changed")
    if previous["config_hash"] != current["config_hash"]:
        reasons.append("config-changed")
        affected.add(("*", "*", "*"))
    if previous["program_hash"] != current["program_hash"]:
        reasons.append("program-changed")
        affected.add(("*", "*", "*"))
    full = bool(reasons)
    return dict(
        changed=changed,
        removed=removed,
        change_kind=("python-change" if "python" in categories else "docs-only" if categories == {"documentation"} else
                     "metadata-only" if full and not categories else "other-change" if categories else "no-op"),
        analysis_scope="full-capture" if full else "none",
        full_analysis_required=full,
        reasons=reasons + (["dependency-closure-unavailable"] if full else []),
        identity_strategy=IDENTITY_STRATEGY,
        affected_embedding_partitions=[dict(repository=r, kind=k, is_test=t) for r, k, t in sorted(affected, key=str)],
    )
