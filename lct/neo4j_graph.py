"""Bounded, version-scoped Neo4j projection of an already published SQLite index.

This module never extracts source or changes the authoritative SQLite snapshot.
Install the optional ``neo4j`` dependency group to use the driver.
"""

import argparse
import json
import os
import sqlite3
import time
from hashlib import sha256
from uuid import uuid4
from contextlib import closing

from .common import ToolError, canonical, config, digest
from .storage import manifest, validate_folder

MAX_QUERY_IDS = 500
MAX_IMPORT_NODES = 50_000
MAX_IMPORT_EDGES = 500_000
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 1024 * 1024
CHUNK_BYTES = 256 * 1024
LEASE_SECONDS = 60
CLAIM_WAIT_SECONDS = 10
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


def _chunks(value):
    """Split canonical JSON into bounded UTF-8-safe properties."""
    data = value.encode('utf-8')
    start = 0
    while start < len(data):
        end = min(start + CHUNK_BYTES, len(data))
        while end < len(data) and data[end] & 0xc0 == 0x80:
            end -= 1
        yield data[start:end].decode('utf-8')
        start = end


def _fence(tx, scope, owner, state):
    # SET takes a Neo4j write lock on the marker until this transaction commits.
    row = tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                 'SET s.lock_nonce=$nonce RETURN s.owner AS owner, '
                 's.complete AS complete, s.state AS state',
                 **scope, nonce=uuid4().hex).single()
    if row is None or row['owner'] != owner or row['complete'] is not False or (
            state is not None and row['state'] != state):
        raise ToolError('Snapshot import ownership lost or candidate changed')
    tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
           'SET s.lease_until=$lease', **scope, lease=time.time() + LEASE_SECONDS).consume()


def _write(session, scope, owner, query, rows=None):
    with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
        _fence(tx, scope, owner, 'writing')
        tx.run(query, **scope, **({'rows': rows} if rows is not None else {})).consume()


def _cleanup(session, scope, owner):
    for pattern, variable in (
        ('(a:LCTNode {namespace:$namespace, version:$version})-[r '
         '{namespace:$namespace, version:$version}]->()', 'r'),
        ('(c:LCTChunk {namespace:$namespace, version:$version})', 'c'),
        ('(e:LCTEdge {namespace:$namespace, version:$version})', 'e'),
        ('(n:LCTNode {namespace:$namespace, version:$version})', 'n'),
    ):
        while True:
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                _fence(tx, scope, owner, 'writing')
                count = tx.run(f'MATCH {pattern} WITH {variable} LIMIT $limit '
                               f'DELETE {variable} RETURN count({variable}) AS removed',
                               **scope, limit=MAX_BATCH_RECORDS).single(strict=True)['removed']
            if count == 0:
                break


def _compare(tx, scope, query, expected):
    actual = iter(tx.run(query, **scope))
    for want in expected:
        got = next(actual, None)
        if got is None or tuple(got.values()) != want:
            raise ToolError('Neo4j import verification mismatch')
    if next(actual, None) is not None:
        raise ToolError('Neo4j import verification extra record')


def _verify(session, scope, owner, nodes, edges, node_ids, metadata):
    # This transaction retains the marker lock for a consistent verification view.
    # It changes only the small marker and does not hold the write batches open.
    with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
        _fence(tx, scope, owner, 'validating')
        _compare(tx, scope,
                 'MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                 'RETURN s.node_count AS nodes, s.edge_count AS edges, '
                 's.native_count AS native, s.chunk_count AS chunks, '
                 's.graph_sha256 AS graph_sha, s.source_sha256 AS source_sha',
                 iter(((len(nodes), len(edges),
                        sum(e.get('source') in node_ids and e.get('target') in node_ids
                            for e in edges),
                        sum(len(list(_chunks(v))) for v in metadata.values()),
                        sha256(metadata['graph'].encode('utf-8')).hexdigest(),
                        sha256(metadata['source'].encode('utf-8')).hexdigest()),)))
        _compare(tx, scope,
                 'MATCH (n:LCTNode {namespace:$namespace, version:$version}) '
                 'RETURN n.node_id AS id, n.kind AS kind, n.repository AS repository, '
                 'n.path AS path, n.qualname AS qualname, n.version_id AS version_id, '
                 'n.raw_json AS raw ORDER BY id',
                 ((n['node_id'], n['kind'], n.get('repository'), n.get('path'),
                   n.get('qualname'), n.get('version_id'), canonical(n))
                  for n in sorted(nodes, key=lambda n: n['node_id'])))
        _compare(tx, scope,
                 'MATCH (e:LCTEdge {namespace:$namespace, version:$version}) '
                 'RETURN e.edge_id AS id, e.kind AS kind, e.source AS source, '
                 'e.target AS target, e.status AS status, e.site_id AS site_id, '
                 'e.unknown_origin AS unknown_origin, e.complete AS complete, '
                 'e.source_version_id AS source_version_id, '
                 'e.target_version_id AS target_version_id, '
                 'e.internal AS internal, e.raw_json AS raw ORDER BY id',
                 ((e['edge_id'], e['kind'], e.get('source'), e.get('target'),
                   e.get('status'), e.get('site_id'), e.get('unknown_origin'),
                   e.get('complete'), e.get('source_version_id'),
                   e.get('target_version_id'),
                   e.get('source') in node_ids and e.get('target') in node_ids,
                   canonical(e)) for e in sorted(edges, key=lambda e: e['edge_id'])))
        _compare(tx, scope,
                 'MATCH (a:LCTNode {namespace:$namespace, version:$version})-[r]->(b) '
                 'RETURN r.edge_id AS id, type(r) AS kind, a.node_id AS source, '
                 'b.node_id AS target, r.namespace AS namespace, r.version AS version, '
                 'b.namespace AS target_namespace, b.version AS target_version '
                 'ORDER BY id',
                 ((e['edge_id'], e['kind'], e['source'], e['target'],
                   scope['namespace'], scope['version'], scope['namespace'], scope['version'])
                  for e in sorted(edges, key=lambda e: e['edge_id']) if
                  e.get('source') in node_ids and e.get('target') in node_ids))
        _compare(tx, scope,
                 'MATCH (a)-[r]->(b:LCTNode {namespace:$namespace, version:$version}) '
                 'WHERE NOT (a:LCTNode AND a.namespace=$namespace AND a.version=$version) '
                 'RETURN r.edge_id AS id', iter(()))
        _compare(tx, scope,
                 'MATCH (c:LCTChunk {namespace:$namespace, version:$version}) '
                 'RETURN c.kind AS kind, c.ordinal AS ordinal, c.data AS data, '
                 'c.sha256 AS sha256 '
                 'ORDER BY kind, ordinal',
                 ((kind, ordinal, part, sha256(part.encode('utf-8')).hexdigest())
                  for kind, value in metadata.items()
                  for ordinal, part in enumerate(_chunks(value))))


def _staged_import(graph_db, scope, nodes, edges, graph, source, fingerprint, node_ids):
    owner = uuid4().hex
    with graph_db.driver.session(database=graph_db.database, fetch_size=64) as session:
        graph_db._schema(session)
        deadline = time.monotonic() + CLAIM_WAIT_SECONDS
        while True:
            now = time.time()
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                row = tx.run(
                    'MERGE (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                    'ON CREATE SET s.fingerprint=$fingerprint, s.complete=false, '
                    "s.owner=$owner, s.lease_until=$lease, s.state='writing', "
                    "s.storage_format='chunks-v1' "
                    'SET s.lock_nonce=$nonce '
                    'RETURN s.fingerprint AS fingerprint, s.complete AS complete, '
                    's.owner AS owner, s.lease_until AS lease',
                    **scope, fingerprint=fingerprint, owner=owner, nonce=uuid4().hex,
                    lease=now + LEASE_SECONDS).single(strict=True)
                if row['fingerprint'] != fingerprint:
                    raise ToolError('Snapshot scope already contains different content')
                if row['complete'] is not False and row['complete'] is not True:
                    raise ToolError('Snapshot scope has invalid completion state')
                if row['complete'] is True:
                    return dict(**scope, fingerprint=fingerprint, nodes=len(nodes),
                                edges=len(edges), already_present=True)
                if row['owner'] == owner:
                    break
                if row['owner'] is None or row['lease'] is None or row['lease'] < now:
                    tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                           "SET s.owner=$owner, s.lease_until=$lease, s.state='writing'",
                           **scope, owner=owner, lease=now + LEASE_SECONDS).consume()
                    break
            if time.monotonic() >= deadline:
                raise ToolError('Snapshot import busy (active writer)')
            time.sleep(.1)
        try:
            _cleanup(session, scope, owner)
            metadata = {kind: canonical(value) for kind, value in
                        (('graph', graph), ('source', source))}
            for kind, label in NODE_LABELS.items():
                rows = (dict(node_id=n['node_id'], kind=n['kind'],
                             repository=n.get('repository'), path=n.get('path'),
                             qualname=n.get('qualname'), version_id=n.get('version_id'),
                             raw=canonical(n)) for n in nodes if n['kind'] == kind)
                for batch in _batches(rows):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row '
                           f'CREATE (n:LCTNode:{label} {{namespace:$namespace, version:$version, '
                           'node_id:row.node_id, kind:row.kind, repository:row.repository, '
                           'path:row.path, qualname:row.qualname, version_id:row.version_id, '
                           'raw_json:row.raw})', batch)
            edge_rows = (dict(edge_id=e['edge_id'], kind=e['kind'], source=e.get('source'),
                              target=e.get('target'), status=e.get('status'),
                              site_id=e.get('site_id'), unknown_origin=e.get('unknown_origin'),
                              complete=e.get('complete'),
                              source_version_id=e.get('source_version_id'),
                              target_version_id=e.get('target_version_id'), raw=canonical(e),
                              internal=e.get('source') in node_ids and
                              e.get('target') in node_ids) for e in edges)
            for batch in _batches(edge_rows):
                _write(session, scope, owner,
                       'UNWIND $rows AS row '
                       'CREATE (e:LCTEdge {namespace:$namespace, version:$version, '
                       'edge_id:row.edge_id, kind:row.kind, source:row.source, '
                       'target:row.target, status:row.status, site_id:row.site_id, '
                       'unknown_origin:row.unknown_origin, complete:row.complete, '
                       'source_version_id:row.source_version_id, '
                       'target_version_id:row.target_version_id, internal:row.internal, '
                       'raw_json:row.raw})', batch)
            for kind in sorted(REL_TYPES):
                rows = (dict(edge_id=e['edge_id'], source=e['source'], target=e['target'])
                        for e in edges if e['kind'] == kind and
                        e.get('source') in node_ids and e.get('target') in node_ids)
                for batch in _batches(rows):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row '
                           'MATCH (a:LCTNode {namespace:$namespace, version:$version, '
                           'node_id:row.source}) '
                           'MATCH (b:LCTNode {namespace:$namespace, version:$version, '
                           'node_id:row.target}) '
                           f'CREATE (a)-[:{kind} {{edge_id:row.edge_id, namespace:$namespace, '
                           'version:$version}]->(b)', batch)
            for kind, value in metadata.items():
                for batch in _batches(dict(kind=kind, ordinal=i, data=part,
                                           sha256=sha256(part.encode('utf-8')).hexdigest())
                                      for i, part in enumerate(_chunks(value))):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row '
                           'CREATE (c:LCTChunk {namespace:$namespace, version:$version, '
                           'kind:row.kind, ordinal:row.ordinal, data:row.data, '
                           'sha256:row.sha256})', batch)
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                _fence(tx, scope, owner, 'writing')
                tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                       "SET s.state='validating', s.node_count=$nodes, s.edge_count=$edges, "
                       's.native_count=$native, s.chunk_count=$chunks, '
                       's.graph_sha256=$graph_sha, '
                       's.source_sha256=$source_sha, s.storage_format=$format',
                       **scope, nodes=len(nodes), edges=len(edges),
                       native=sum(e.get('source') in node_ids and e.get('target') in node_ids
                                  for e in edges),
                       chunks=sum(len(list(_chunks(v))) for v in metadata.values()),
                       graph_sha=sha256(metadata['graph'].encode('utf-8')).hexdigest(),
                       source_sha=sha256(metadata['source'].encode('utf-8')).hexdigest(),
                       format='chunks-v1').consume()
            _verify(session, scope, owner, nodes, edges, node_ids, metadata)
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                _fence(tx, scope, owner, 'validating')
                tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                       "SET s.state='complete', s.complete=true, s.owner=null, "
                       's.lease_until=null', **scope).consume()
        except Exception:
            try:
                with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                    _fence(tx, scope, owner, None)
                    tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                           "SET s.state='failed', s.owner=null, s.lease_until=null",
                           **scope).consume()
            except Exception:
                pass
            raise
    return dict(**scope, fingerprint=fingerprint, nodes=len(nodes),
                edges=len(edges), already_present=False)


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
            ("lct_chunk_scope", "LCTChunk", "s.namespace, s.version, s.kind, s.ordinal"),
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
        del payload
        node_ids = {n["node_id"] for n in nodes}
        if len(node_ids) != len(nodes) or len({e["edge_id"] for e in edges}) != len(edges):
            raise ToolError("Duplicate graph identity")
        return _staged_import(self, scope, nodes, edges, graph, source, fingerprint, node_ids)
    def _read(self, namespace, version, query, **params):
        scope = _scope(namespace, version)
        with self.driver.session(database=self.database, default_access_mode="READ",
                                 fetch_size=64) as session:
            # No fallback to current and no results from incomplete transactions.
            found = session.run(
                "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
                "RETURN s.fingerprint AS fingerprint", **scope,
            ).single()
            if found is None:
                raise ToolError("Neo4j snapshot missing or incomplete")
            return found["fingerprint"], list(session.run(query, **scope, **params))

    def snapshot_fingerprint(self, namespace, version):
        """Read only the identity marker of a complete, explicitly scoped snapshot."""
        scope = _scope(namespace, version)
        with self.driver.session(database=self.database, default_access_mode="READ",
                                 fetch_size=64) as session:
            row = session.run(
                "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
                "RETURN s.fingerprint AS fingerprint", **scope,
            ).single()
            if row is None or not isinstance(row["fingerprint"], str) or not row["fingerprint"]:
                raise ToolError("Neo4j snapshot missing or incomplete")
            return row["fingerprint"]

    def snapshot_info(self, namespace, version):
        fingerprint, rows = self._read(namespace, version,
            "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
            "RETURN s.node_count AS nodes, s.edge_count AS edges, "
            "s.graph_json AS graph, s.source_json AS source, "
            "s.storage_format AS storage_format")
        row = rows[0]
        if row['storage_format'] == 'chunks-v1':
            _, parts = self._read(namespace, version,
                "MATCH (c:LCTChunk {namespace:$namespace, version:$version}) "
                "RETURN c.kind AS kind, c.ordinal AS ordinal, c.data AS data "
                "ORDER BY kind, ordinal")
            content = {}
            for kind in ('graph', 'source'):
                ordered = [part for part in parts if part['kind'] == kind]
                if not ordered or [part['ordinal'] for part in ordered] != list(range(len(ordered))):
                    raise ToolError('Neo4j snapshot metadata incomplete')
                content[kind] = json.loads(''.join(part['data'] for part in ordered))
        else:
            content = dict(graph=json.loads(row['graph']), source=json.loads(row['source']))
        return dict(namespace=namespace, version=version, fingerprint=fingerprint,
                    nodes=row["nodes"], edges=row["edges"], **content)

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
