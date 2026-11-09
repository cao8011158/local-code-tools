"""Bounded, fail-closed rebinding of captured Python definition evidence.

The caller must separately certify that a record's owner is unaffected by the
change scheduler. Unchanged ASTs alone do not establish semantic independence.
"""

import ast
from copy import deepcopy


class EvidenceReuseRejected(ValueError):
    """The owning call site must be analyzed again in the new capture."""


class RebindContext:
    """Prepare identity indexes once; memoize per-definition AST checks."""

    def __init__(self, *, old_nodes, new_nodes, old_trees, new_trees, selected_paths,
                 verified_sources=None):
        self.old_nodes, self.new_nodes = old_nodes, new_nodes
        self.old_trees, self.new_trees = old_trees, new_trees
        self.selected_paths = selected_paths
        # Mapping (repository,path) -> (old captured-text digest, new digest).
        # The source preparation caller must hash both captured byte strings.
        self.verified_sources = verified_sources or {}
        self.old_by_key, self.new_by_key = {}, {}
        self._matches = {}
        self.match_evaluations = 0
        for nodes, index in ((old_nodes, self.old_by_key), (new_nodes, self.new_by_key)):
            for node in nodes.values():
                key = (node.get("repository"), node.get("path"),
                       node.get("qualname"), node.get("kind"))
                index.setdefault(key, []).append(node)

    def matched(self, ident):
        if ident in self._matches:
            return self._matches[ident]
        self.match_evaluations += 1
        old = self.old_nodes.get(ident)
        if old is None:
            raise EvidenceReuseRejected("old definition missing")
        key = old.get("repository"), old.get("path"), old.get("qualname"), old.get("kind")
        if len(self.old_by_key.get(key, ())) != 1 or len(self.new_by_key.get(key, ())) != 1:
            raise EvidenceReuseRejected("ambiguous or deleted definition identity")
        new = self.new_by_key[key][0]
        if new.get("node_id") != ident or not key[1]:
            raise EvidenceReuseRejected("definition identity moved")
        for field in ("definition_line", "start", "column", "end", "end_column", "fingerprint"):
            if old.get(field) != new.get(field):
                raise EvidenceReuseRejected("definition span or fingerprint changed")
        prior, current = self.old_trees.get(ident), self.new_trees.get(ident)
        if prior is None or current is None:
            source = old["repository"], old["path"]
            fingerprints = self.verified_sources.get(source)
            if (not isinstance(fingerprints, tuple) or len(fingerprints) != 2
                    or any(not isinstance(hash_value, str) or not hash_value
                           for hash_value in fingerprints)
                    or fingerprints[0] != fingerprints[1]
                    or old.get("source_sha256") != fingerprints[0]
                    or new.get("source_sha256") != fingerprints[1]):
                raise EvidenceReuseRejected("definition source not verified")
        elif ast.dump(prior, include_attributes=False) != ast.dump(current, include_attributes=False):
            raise EvidenceReuseRejected("definition AST changed")
        self._matches[ident] = (old, new)
        return old, new

    def rebind(self, record, *, owner_id):
        """Return an independent copy with validated, typed definition versions.

        The only accepted version-bearing schema is a Jedi raw mapping marked
        exact-captured-definition. Other shapes fail closed.
        """
        owner_old, _ = self.matched(owner_id)
        if ((owner_old["repository"], owner_old["path"]) in self.selected_paths
                or owner_old["path"] in self.selected_paths):
            # Path-only input remains a conservative legacy experiment guard;
            # production supplies repository/path identities exclusively.
            raise EvidenceReuseRejected("owner selected for reanalysis")

        def walk(value, parent=None):
            if isinstance(value, list):
                return [walk(item, parent) for item in value]
            if not isinstance(value, dict):
                return deepcopy(value)
            result = {key: walk(item, key) for key, item in value.items() if key != "version_id"}
            if "version_id" not in value:
                return result
            target = None
            raw_keys = {"column", "full_name", "line", "mapping", "module_path",
                        "name", "repository", "source_sha256", "target", "type", "version_id"}
            keys = set(value)
            parameter_error = (keys == raw_keys | {"parameters", "parameters_error"}
                               and isinstance(value["parameters_error"], str)
                               and bool(value["parameters_error"])
                               and value["parameters"] == [])
            if (parent == "raw" and value.get("mapping") == "exact-captured-definition"
                    and (keys in (raw_keys, raw_keys | {"parameters"}) or
                         parameter_error)):
                target = value["target"]
            else:
                raise EvidenceReuseRejected("unknown version reference shape")
            if not isinstance(target, str):
                raise EvidenceReuseRejected("invalid definition target")
            prior, current = self.matched(target)
            if value["version_id"] != prior.get("version_id"):
                raise EvidenceReuseRejected("old definition stamp mismatch")
            if parent == "raw":
                if value["source_sha256"] != prior.get("source_sha256"):
                    raise EvidenceReuseRejected("old raw source fingerprint mismatch")
                result["source_sha256"] = current["source_sha256"]
            result["version_id"] = current["version_id"]
            return result

        return walk(record)


def rebind_evidence(record, *, owner_id, old_nodes, new_nodes, old_trees,
                    new_trees, selected_paths):
    """One-off convenience API; use RebindContext for repeated records."""
    return RebindContext(old_nodes=old_nodes, new_nodes=new_nodes,
                         old_trees=old_trees, new_trees=new_trees,
                         selected_paths=selected_paths).rebind(record, owner_id=owner_id)
