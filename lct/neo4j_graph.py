"""Bounded, version-scoped Neo4j projection of an already published SQLite index.

This module never extracts source or changes the authoritative SQLite snapshot.
Install the optional ``neo4j`` dependency group to use the driver.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing

from .common import ToolError, canonical, config, digest
from .storage import manifest, validate_folder

MAX_QUERY_IDS = 500
MAX_IMPORT_NODES = 50_000
MAX_IMPORT_EDGES = 500_000
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 1024 * 1024
IMPORT_TIMEOUT_SECONDS = 300
MAX_RESULTS = 5000
NODE_LABELS = {
    "repository": "Repository", "module": "Module", "class": "Class",
    "function": "Function", "documentsection": "DocumentSection",
}
REL_TYPES = frozenset({"CONTAINS", "IMPORTS", "CALLS", "INHERITS", "REFERENCES",
                       "WRAPS", "CONTEXT_ENTERS"})


def load_snapshot(c, version):
    """Validate a named complete snapshot and read only its persisted raw graph data."""
    if not isinstance(version, str) or not version:
        raise ToolError("Explicit index version required")
    folder, m = manifest(c, version)
    validate_folder(folder, m, full=True)
    uri = (folder / "catalog.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        nodes = [json.loads(row[0]) for row in db.execute("select data from nodes order by node_id")]
        edges = [json.loads(row[0]) for row in db.execute("select data from edges order by edge_id")]
    _import_counts(nodes, edges)
    if len(nodes) != m["node_count"] or len(edges) != sum(m["edges"].values()):
        raise ToolError("Catalog graph counts mismatch")
    if any(n.get("kind") not in NODE_LABELS for n in nodes):
        raise ToolError("Unsupported node kind")
    if any(e.get("kind") not in REL_TYPES for e in edges):
        raise ToolError("Unsupported relationship kind")
    graph = m["graph"]  # Includes the complete site inventory and unresolved reasons.
    source = {k: m[k] for k in ("repositories", "source_fingerprint", "files")}
    payload = _snapshot_payload(nodes, edges, graph, source)
    fingerprint = digest(payload)
    return dict(version=version, nodes=nodes, edges=edges, graph=graph, source=source,
                fingerprint=fingerprint)


def _import_counts(nodes, edges):
    if len(nodes) > MAX_IMPORT_NODES or len(edges) > MAX_IMPORT_EDGES:
        raise ToolError("Graph import limit exceeded (50000 nodes, 500000 edges)")


def _snapshot_payload(nodes, edges, graph, source):
    payload = canonical(dict(nodes=nodes, edges=edges, graph=graph, source=source))
    if len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ToolError("Graph import canonical snapshot exceeds 128 MiB")
    return payload


def _batches(rows):
    """Bound each parameter batch by record count and UTF-8 JSON size."""
    batch, size = [], 0
    for row in rows:
        row_size = len(canonical(row).encode("utf-8"))
        if row_size > MAX_BATCH_BYTES:
            raise ToolError("Graph import record exceeds 1 MiB batch limit")
        if batch and (len(batch) >= MAX_BATCH_RECORDS or size + row_size > MAX_BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def _scope(namespace, version):
    if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 200:
        raise ToolError("Explicit namespace required (at most 200 characters)")
    if not isinstance(version, str) or not version.strip() or len(version) > 200:
        raise ToolError("Explicit index version required (at most 200 characters)")
    return {"namespace": namespace, "version": version}


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_RESULTS:
        raise ToolError("limit must be between 1 and 5000")
    return value


def _ids(ids):
    if not isinstance(ids, (list, tuple)) or len(ids) > MAX_QUERY_IDS or any(
        not isinstance(i, str) or not i for i in ids
    ):
        raise ToolError("ids must be a list of at most 500 nonempty strings")
    return list(dict.fromkeys(ids))


class Neo4jGraph:
    """Owned Neo4j driver; every read and write has an explicit namespace/version."""

    def __init__(self, uri, user, password, database):
        if not all(isinstance(x, str) and x for x in (uri, user, password, database)):
            raise ToolError("Neo4j URI, user, password and database are required")
        from neo4j import GraphDatabase

        self.database = database
        self.driver = GraphDatabase.driver(uri, auth=(user, password),
                                           connection_timeout=10, max_connection_pool_size=5)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.driver.close()

    def _schema(self, session):
        # Fixed DDL identifiers; constraints are idempotent and enforce concurrent MERGE uniqueness.
        for name, label, keys in (
            ("lct_snapshot_scope", "LCTSnapshot", "s.namespace, s.version"),
            ("lct_node_scope", "LCTNode", "s.namespace, s.version, s.node_id"),
            ("lct_edge_scope", "LCTEdge", "s.namespace, s.version, s.edge_id"),
        ):
            session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (s:{label}) "
                        f"REQUIRE ({keys}) IS UNIQUE").consume()

    def import_snapshot(self, namespace, version, snapshot):
        scope = _scope(namespace, version)
        if not isinstance(snapshot, dict) or snapshot.get("version") != version:
            raise ToolError("Snapshot index version mismatch")
        nodes, edges, graph, source = (snapshot[k] for k in ("nodes", "edges", "graph", "source"))
        _import_counts(nodes, edges)
        if any(n.get("kind") not in NODE_LABELS for n in nodes) or any(
            e.get("kind") not in REL_TYPES for e in edges
        ):
            raise ToolError("Unsupported graph kind")
        payload = _snapshot_payload(nodes, edges, graph, source)
        fingerprint = digest(payload)
        if fingerprint != snapshot.get("fingerprint"):
            raise ToolError("Snapshot fingerprint mismatch")
        node_ids = {n["node_id"] for n in nodes}
        if len(node_ids) != len(nodes) or len({e["edge_id"] for e in edges}) != len(edges):
            raise ToolError("Duplicate graph identity")
        # Prepare all parameter batches before the first write. A single oversized record
        # cannot leave even an incomplete scope behind.
        node_batches = {
            kind: list(_batches(
                dict(node_id=n["node_id"], kind=n["kind"],
                     repository=n.get("repository"), path=n.get("path"),
                     qualname=n.get("qualname"), version_id=n.get("version_id"),
                     raw=canonical(n))
                for n in nodes if n["kind"] == kind))
            for kind in NODE_LABELS
        }
        edge_batches = list(_batches(
            dict(edge_id=e["edge_id"], kind=e["kind"], source=e.get("source"),
                 target=e.get("target"), status=e.get("status"), site_id=e.get("site_id"),
                 unknown_origin=e.get("unknown_origin"), complete=e.get("complete"),
                 source_version_id=e.get("source_version_id"),
                 target_version_id=e.get("target_version_id"), raw=canonical(e),
                 internal=e.get("source") in node_ids and e.get("target") in node_ids)
            for e in edges))
        relation_batches = {
            kind: list(_batches(
                dict(edge_id=e["edge_id"], source=e["source"], target=e["target"])
                for e in edges if e["kind"] == kind and
                e.get("source") in node_ids and e.get("target") in node_ids))
            for kind in sorted(REL_TYPES)
        }
        with self.driver.session(database=self.database) as session:
            self._schema(session)
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                row = tx.run(
                    "MERGE (s:LCTSnapshot {namespace:$namespace, version:$version}) "
                    "ON CREATE SET s.fingerprint=$fingerprint, s.complete=false "
                    "RETURN s.fingerprint AS fingerprint, s.complete AS complete",
                    **scope, fingerprint=fingerprint,
                ).single(strict=True)
                if row["fingerprint"] != fingerprint or row["complete"] is not False and row["complete"] is not True:
                    raise ToolError("Snapshot scope already contains different content")
                if row["complete"]:
                    return dict(**scope, fingerprint=fingerprint, nodes=len(nodes),
                                edges=len(edges), already_present=True)
                for kind, batches in node_batches.items():
                    label = NODE_LABELS[kind]  # fixed whitelist, never input text in Cypher
                    for batch in batches:
                        tx.run(
                            "UNWIND $rows AS row "
                            f"CREATE (n:LCTNode:{label} {{namespace:$namespace, version:$version, "
                            "node_id:row.node_id, kind:row.kind, repository:row.repository, "
                            "path:row.path, qualname:row.qualname, version_id:row.version_id, "
                            "raw_json:row.raw})",
                            **scope, rows=batch,
                        ).consume()
                for batch in edge_batches:
                    tx.run(
                        "UNWIND $rows AS row "
                        "CREATE (e:LCTEdge {namespace:$namespace, version:$version, "
                        "edge_id:row.edge_id, kind:row.kind, source:row.source, "
                        "target:row.target, status:row.status, site_id:row.site_id, "
                        "unknown_origin:row.unknown_origin, complete:row.complete, "
                        "source_version_id:row.source_version_id, "
                        "target_version_id:row.target_version_id, internal:row.internal, "
                        "raw_json:row.raw})",
                        **scope, rows=batch,
                    ).consume()
                for kind, batches in relation_batches.items():
                    for batch in batches:
                        tx.run(
                            "UNWIND $rows AS row "
                            "MATCH (a:LCTNode {namespace:$namespace, version:$version, "
                            "node_id:row.source}) "
                            "MATCH (b:LCTNode {namespace:$namespace, version:$version, "
                            "node_id:row.target}) "
                            f"CREATE (a)-[:{kind} {{edge_id:row.edge_id, namespace:$namespace, "
                            "version:$version}]->(b)",
                            **scope, rows=batch,
                        ).consume()
                tx.run(
                    "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) "
                    "SET s.graph_json=$graph, s.source_json=$source, "
                    "s.node_count=$nodes, s.edge_count=$edges, s.complete=true",
                    **scope, graph=canonical(graph), source=canonical(source),
                    nodes=len(nodes), edges=len(edges),
                ).consume()
        return dict(**scope, fingerprint=fingerprint, nodes=len(nodes),
                    edges=len(edges), already_present=False)

    def _read(self, namespace, version, query, **params):
        scope = _scope(namespace, version)
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            # No fallback to current and no results from incomplete transactions.
            found = session.run(
                "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
                "RETURN s.fingerprint AS fingerprint", **scope,
            ).single()
            if found is None:
                raise ToolError("Neo4j snapshot missing or incomplete")
            return found["fingerprint"], list(session.run(query, **scope, **params))

    def snapshot_info(self, namespace, version):
        fingerprint, rows = self._read(namespace, version,
            "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
            "RETURN s.node_count AS nodes, s.edge_count AS edges, "
            "s.graph_json AS graph, s.source_json AS source")
        row = rows[0]
        return dict(namespace=namespace, version=version, fingerprint=fingerprint,
                    nodes=row["nodes"], edges=row["edges"], graph=json.loads(row["graph"]),
                    source=json.loads(row["source"]))

    def list_nodes(self, namespace, version, kind=None, repository=None, limit=100):
        if kind is not None and kind not in NODE_LABELS:
            raise ToolError("Unsupported node kind")
        if repository is not None and not isinstance(repository, str):
            raise ToolError("repository must be a string")
        limit = _limit(limit)
        _, rows = self._read(namespace, version,
            "MATCH (n:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE ($kind IS NULL OR n.kind=$kind) AND "
            "($repository IS NULL OR n.repository=$repository) "
            "RETURN n.raw_json AS raw ORDER BY n.node_id LIMIT $fetch",
            kind=kind, repository=repository, fetch=limit + 1)
        return dict(nodes=[json.loads(row["raw"]) for row in rows[:limit]],
                    has_more=len(rows) > limit)

    def get_nodes(self, namespace, version, ids):
        ids = _ids(ids)
        _, rows = self._read(namespace, version,
            "MATCH (n:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE n.node_id IN $ids RETURN n.node_id AS id, n.raw_json AS raw", ids=ids)
        by_id = {row["id"]: json.loads(row["raw"]) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    def get_relations(self, namespace, version, ids, types=None, direction="both", limit=100):
        ids = _ids(ids)
        if direction not in ("in", "out", "both"):
            raise ToolError("direction must be in, out or both")
        if types is not None and (not isinstance(types, (list, tuple)) or
                                  any(t not in REL_TYPES for t in types)):
            raise ToolError("Unsupported relationship type")
        limit = _limit(limit)
        params = dict(ids=ids, types=list(types) if types is not None else None,
                      direction=direction, fetch=limit + 1)
        _, internal = self._read(namespace, version,
            "MATCH (a:LCTNode {namespace:$namespace, version:$version})-[r]->"
            "(b:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE type(r) IN $allowed AND ($types IS NULL OR type(r) IN $types) AND "
            "(($direction='out' AND a.node_id IN $ids) OR "
            "($direction='in' AND b.node_id IN $ids) OR "
            "($direction='both' AND (a.node_id IN $ids OR b.node_id IN $ids))) "
            "MATCH (e:LCTEdge {namespace:$namespace, version:$version, edge_id:r.edge_id}) "
            "RETURN e.edge_id AS id, e.raw_json AS raw ORDER BY id LIMIT $fetch",
            **params, allowed=sorted(REL_TYPES))
        _, external = self._read(namespace, version,
            "MATCH (e:LCTEdge {namespace:$namespace, version:$version, internal:false}) "
            "WHERE ($types IS NULL OR e.kind IN $types) AND "
            "(($direction='out' AND e.source IN $ids) OR "
            "($direction='in' AND e.target IN $ids) OR "
            "($direction='both' AND (e.source IN $ids OR e.target IN $ids))) "
            "RETURN e.edge_id AS id, e.raw_json AS raw ORDER BY id LIMIT $fetch", **params)
        combined = {row["id"]: json.loads(row["raw"]) for row in [*internal, *external]}
        ordered = [combined[k] for k in sorted(combined)]
        return dict(edges=ordered[:limit], has_more=len(ordered) > limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded Neo4j projection of a published LCT snapshot")
    parser.add_argument("--config", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import")
    commands.add_parser("info")
    listing = commands.add_parser("nodes")
    listing.add_argument("--kind", choices=NODE_LABELS)
    listing.add_argument("--repository")
    listing.add_argument("--limit", type=int, default=100)
    relations = commands.add_parser("relations")
    relations.add_argument("ids", nargs="+")
    relations.add_argument("--types", nargs="*", choices=sorted(REL_TYPES))
    relations.add_argument("--direction", choices=("in", "out", "both"), default="both")
    relations.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    uri, user, password = (os.getenv(k) for k in
                           ("LCT_NEO4J_URI", "LCT_NEO4J_USER", "LCT_NEO4J_PASSWORD"))
    try:
        c = config(args.config)
        with Neo4jGraph(uri, user, password, args.database) as graph:
            if args.command == "import":
                result = graph.import_snapshot(args.namespace, args.version,
                                               load_snapshot(c, args.version))
            elif args.command == "info":
                result = graph.snapshot_info(args.namespace, args.version)
            elif args.command == "nodes":
                result = graph.list_nodes(args.namespace, args.version, args.kind,
                                          args.repository, args.limit)
            else:
                result = graph.get_relations(args.namespace, args.version, args.ids,
                                             args.types, args.direction, args.limit)
        print(canonical(result))
    except (ToolError, ValueError, KeyError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
