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
from .storage import manifest, validate_folder, graph_detail, source_files

PROJECTION_SCHEMA = 'native-boundary-v2'
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
MAX_REPLY_DATA_BYTES = 64 * 1024
PAGE_FETCH = 17  # At most 16 records plus one lookahead; large raw records stay bounded.
NODE_LABELS = {
    "repository": "Repository", "module": "Module", "class": "Class",
    "function": "Function", "documentsection": "DocumentSection",
}
REL_TYPES = frozenset({"CONTAINS", "IMPORTS", "CALLS", "INHERITS", "REFERENCES",
                       "WRAPS", "CONTEXT_ENTERS", "LOOKUP_IN"})


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
    graph = graph_detail(folder, m)  # Explicit full import retains all unresolved evidence.
    source = {"repositories": m["repositories"],
              "source_fingerprint": m["source_fingerprint"],
              "files": source_files(folder, m)}
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


def _after(value):
    if value is not None and (not isinstance(value, str) or len(value) > 4096):
        raise ToolError("cursor must be a string of at most 4096 characters")
    return value


def _bounded_page(rows, key, limit, cursor=None):
    """Budget the serialized data envelope, preserving an exact next position."""
    items = []
    for row in rows:
        if row['raw'] is None:
            if items:
                break
            raise ToolError('Single graph record exceeds reply byte limit')
        item = json.loads(row['raw'])
        trial = {key: [*items, item], 'has_more': True, 'next_cursor': row['id']}
        if len(canonical(trial).encode('utf-8')) > MAX_REPLY_DATA_BYTES:
            if not items:
                raise ToolError('Single graph record exceeds reply byte limit')
            break
        items.append(item)
        if len(items) >= min(limit, PAGE_FETCH - 1):
            break
    more = len(rows) > len(items)
    return {key: items, 'has_more': more,
            'next_cursor': rows[len(items) - 1]['id'] if more and items else None}


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


def _write(session, scope, owner, query, rows=None, state="writing"):
    with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
        _fence(tx, scope, owner, state)
        tx.run(query, **scope, **({'rows': rows} if rows is not None else {})).consume()


def _cleanup(session, scope, owner):
    for pattern, variable in (
        ('(a:LCTNode {namespace:$namespace, version:$version})-[r '
         '{namespace:$namespace, version:$version}]->()', 'r'),
        ('(a:LCTBoundary {namespace:$namespace, version:$version})-[r '
         '{namespace:$namespace, version:$version}]->()', 'r'),
        ('(c:LCTChunk {namespace:$namespace, version:$version})', 'c'),
        ('(e:LCTEdge {namespace:$namespace, version:$version})', 'e'),
        ('(b:LCTBoundary {namespace:$namespace, version:$version})', 'b'),
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
                 's.native_count AS native, s.boundary_count AS boundary_count, '
                 's.projection_schema AS projection_schema, s.chunk_count AS chunks, '
                 's.graph_sha256 AS graph_sha, s.source_sha256 AS source_sha',
                 iter(((len(nodes), len(edges), len(edges), len(_boundaries(edges, node_ids)),
                        PROJECTION_SCHEMA,
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
                 'e.internal AS internal, e.source_boundary_id AS source_boundary, '
                 'e.target_boundary_id AS target_boundary, e.raw_json AS raw ORDER BY id',
                 ((e['edge_id'], e['kind'], e.get('source'), e.get('target'),
                   e.get('status'), e.get('site_id'), e.get('unknown_origin'),
                   e.get('complete'), e.get('source_version_id'),
                   e.get('target_version_id'),
                   e.get('source') in node_ids and e.get('target') in node_ids,
                   _boundary_id(e, 'source', node_ids), _boundary_id(e, 'target', node_ids),
                   canonical(e)) for e in sorted(edges, key=lambda e: e['edge_id'])))
        boundary = _boundaries(edges, node_ids)
        _compare(tx, scope,
                 'MATCH (b:LCTBoundary {namespace:$namespace, version:$version}) '
                 'RETURN b.boundary_id AS id, b.endpoint_id AS endpoint, '
                 'b.category AS category, b.lookup_repository AS lookup_repository, '
                 'b.lookup_module AS lookup_module, b.lookup_name AS lookup_name, '
                 'b.lookup_status AS lookup_status, b.lookup_reason AS lookup_reason ORDER BY id',
                 ((b['boundary_id'], b['endpoint_id'], b['category'],
                   b.get('lookup_repository'), b.get('lookup_module'),
                   b.get('lookup_name'), b.get('lookup_status'),
                   b.get('lookup_reason')) for b in
                  sorted(boundary.values(), key=lambda b: b['boundary_id'])))
        _compare(tx, scope,
                 'MATCH (a)-[r {namespace:$namespace, version:$version}]->(b) '
                 'RETURN r.edge_id AS id, type(r) AS kind, '
                 'coalesce(a.node_id,a.endpoint_id) AS source, '
                 'coalesce(b.node_id,b.endpoint_id) AS target, '
                 'r.source_boundary_id AS source_boundary, '
                 'r.target_boundary_id AS target_boundary, '
                 'a.boundary_id AS actual_source_boundary, '
                 'b.boundary_id AS actual_target_boundary, '
                 'a.namespace AS source_namespace, a.version AS source_version, '
                 'b.namespace AS target_namespace, b.version AS target_version '
                 'ORDER BY id',
                 ((e['edge_id'], e['kind'], e.get('source'), e.get('target'),
                   _boundary_id(e, 'source', node_ids), _boundary_id(e, 'target', node_ids),
                   _boundary_id(e, 'source', node_ids), _boundary_id(e, 'target', node_ids),
                   scope['namespace'], scope['version'], scope['namespace'], scope['version'])
                  for e in sorted(edges, key=lambda e: e['edge_id'])))
        _compare(tx, scope,
                 'MATCH (a)-[r]->(b) WHERE '
                 '(a:LCTNode OR a:LCTBoundary) AND a.namespace=$namespace AND a.version=$version AND '
                 '(r.namespace IS NULL OR r.version IS NULL OR '
                 'r.namespace <> $namespace OR r.version <> $version) '
                 'RETURN r.edge_id AS id', iter(()))
        _compare(tx, scope,
                 'MATCH (a)-[r]->(b {namespace:$namespace, version:$version}) '
                 'WHERE r.namespace=$namespace AND r.version=$version AND '
                 '(a.namespace IS NULL OR a.version IS NULL OR '
                 'a.namespace <> $namespace OR a.version <> $version) '
                 'RETURN r.edge_id AS id', iter(()))
        _compare(tx, scope,
                 'MATCH (c:LCTChunk {namespace:$namespace, version:$version}) '
                 'RETURN c.kind AS kind, c.ordinal AS ordinal, c.data AS data, '
                 'c.sha256 AS sha256 '
                 'ORDER BY kind, ordinal',
                 ((kind, ordinal, part, sha256(part.encode('utf-8')).hexdigest())
                  for kind, value in metadata.items()
                  for ordinal, part in enumerate(_chunks(value))))


def _boundary_id(edge, side, node_ids):
    endpoint = edge.get(side)
    if endpoint in node_ids:
        return None
    if isinstance(endpoint, str) and endpoint:
        return 'external:' + endpoint
    return 'unresolved:' + edge['edge_id'] + ':' + side


def _boundaries(edges, node_ids):
    by_id = {}
    for edge in edges:
        for side in ('source', 'target'):
            key = _boundary_id(edge, side, node_ids)
            if key is not None:
                endpoint = edge.get(side)
                lookup = edge.get('lookup') if isinstance(endpoint, str) and endpoint.startswith(
                    'boundary:unresolved-import:') else None
                record = dict(boundary_id=key, endpoint_id=endpoint,
                              category='unresolved' if lookup or not endpoint else 'external',
                              lookup_repository=lookup.get('repository') if lookup else None,
                              lookup_module=lookup.get('module') if lookup else None,
                              lookup_name=lookup.get('name') if lookup else None,
                              lookup_status=edge.get('lookup_status') if lookup else None,
                              lookup_reason='named-import-unresolved' if lookup else None)
                if key in by_id and by_id[key] != record:
                    raise ToolError('Inconsistent boundary lookup identity')
                by_id[key] = record
    return by_id


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
                    "s.storage_format='chunks-v1', s.projection_schema=$projection_schema "
                    'SET s.lock_nonce=$nonce '
                    'RETURN s.fingerprint AS fingerprint, s.complete AS complete, '
                    's.owner AS owner, s.lease_until AS lease, s.projection_schema AS projection_schema',
                    **scope, fingerprint=fingerprint, projection_schema=PROJECTION_SCHEMA, owner=owner, nonce=uuid4().hex,
                    lease=now + LEASE_SECONDS).single(strict=True)
                if row['projection_schema'] != PROJECTION_SCHEMA:
                    raise ToolError('Snapshot scope uses a different projection; select a fresh namespace')
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
            boundary = _boundaries(edges, node_ids)
            for batch in _batches(boundary.values()):
                _write(session, scope, owner,
                       'UNWIND $rows AS row CREATE (b:LCTBoundary '
                       '{namespace:$namespace, version:$version, boundary_id:row.boundary_id, '
                       'endpoint_id:row.endpoint_id, category:row.category, '
                       'lookup_repository:row.lookup_repository, lookup_module:row.lookup_module, '
                       'lookup_name:row.lookup_name, lookup_status:row.lookup_status, '
                       'lookup_reason:row.lookup_reason})', batch)
            edge_rows = (dict(edge_id=e['edge_id'], kind=e['kind'], source=e.get('source'),
                              target=e.get('target'), status=e.get('status'),
                              site_id=e.get('site_id'), unknown_origin=e.get('unknown_origin'),
                              complete=e.get('complete'),
                              source_version_id=e.get('source_version_id'),
                              target_version_id=e.get('target_version_id'),
                              source_boundary=_boundary_id(e, 'source', node_ids),
                              target_boundary=_boundary_id(e, 'target', node_ids), raw=canonical(e),
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
                       'source_boundary_id:row.source_boundary, target_boundary_id:row.target_boundary, '
                       'raw_json:row.raw})', batch)
            for kind in sorted(REL_TYPES):
                rows = (dict(edge_id=e['edge_id'], source=e.get('source'), target=e.get('target'),
                             source_boundary=_boundary_id(e, 'source', node_ids),
                             target_boundary=_boundary_id(e, 'target', node_ids))
                        for e in edges if e['kind'] == kind)
                for batch in _batches(rows):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row '
                           'OPTIONAL MATCH (an:LCTNode {namespace:$namespace, version:$version, node_id:row.source}) '
                           'OPTIONAL MATCH (ab:LCTBoundary {namespace:$namespace, version:$version, boundary_id:row.source_boundary}) '
                           'OPTIONAL MATCH (bn:LCTNode {namespace:$namespace, version:$version, node_id:row.target}) '
                           'OPTIONAL MATCH (bb:LCTBoundary {namespace:$namespace, version:$version, boundary_id:row.target_boundary}) '
                           'WITH row, coalesce(an, ab) AS a, coalesce(bn, bb) AS b '
                           f'CREATE (a)-[:{kind} {{edge_id:row.edge_id, namespace:$namespace, '
                           'version:$version, source_boundary_id:row.source_boundary, '
                           'target_boundary_id:row.target_boundary}]->(b)', batch)
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
                       's.native_count=$native, s.boundary_count=$boundary_count, s.chunk_count=$chunks, '
                       's.graph_sha256=$graph_sha, '
                       's.source_sha256=$source_sha, s.source_fingerprint=$source_fingerprint, '
                       's.source_repository_count=$source_repository_count, '
                       's.storage_format=$format',
                       **scope, nodes=len(nodes), edges=len(edges),
                       native=len(edges),
                       boundary_count=len(boundary),
                       chunks=sum(len(list(_chunks(v))) for v in metadata.values()),
                       graph_sha=sha256(metadata['graph'].encode('utf-8')).hexdigest(),
                       source_sha=sha256(metadata['source'].encode('utf-8')).hexdigest(),
                       source_fingerprint=source.get('source_fingerprint'),
                       source_repository_count=(len(source['repositories']) if
                                                isinstance(source.get('repositories'), dict) else None),
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


# Fixed Neo4j 5.26-compatible templates for the official neo4j/mcp read-cypher tool.
# Each branch starts at a scoped identity/index lookup; no full relationship or edge scan.
def relation_queries(direction):
    if direction not in ("in", "out", "both"):
        raise ToolError("direction must be in, out or both")
    native_branches = []
    external_branches = []
    for side in (("out", "in") if direction == "both" else (direction,)):
        node_pattern = ("(a:LCTNode {namespace:$namespace, version:$version, node_id:wanted})"
                        "-[r]->(b:LCTNode {namespace:$namespace, version:$version})" if side == "out" else
                        "(a:LCTNode {namespace:$namespace, version:$version})"
                        "-[r]->(b:LCTNode {namespace:$namespace, version:$version, node_id:wanted})")
        native_branches.append(
            "UNWIND $ids AS wanted MATCH " + node_pattern +
            " WHERE r.namespace=$namespace AND r.version=$version AND type(r) IN $allowed "
            "RETURN r.edge_id AS edge_id")
        external_branches.append(
            "UNWIND $ids AS wanted MATCH (e:LCTEdge {namespace:$namespace, version:$version, "
            + ("source" if side == "out" else "target") + ":wanted}) "
            "WHERE e.internal=false RETURN e.edge_id AS edge_id")
    suffix = (
        " WITH DISTINCT edge_id "
        "MATCH (e:LCTEdge {namespace:$namespace, version:$version, edge_id:edge_id}) "
        "WHERE ($types IS NULL OR e.kind IN $types) AND "
        "($cursor IS NULL OR e.edge_id > $cursor) "
        "RETURN e.edge_id AS id, "
        "CASE WHEN size(e.raw_json)>65536 THEN null ELSE e.raw_json END AS raw "
        "ORDER BY id LIMIT $fetch")
    return tuple("CALL () { " + " UNION ".join(branches) + " }" + suffix
                 for branches in (native_branches, external_branches))


def native_relation_query(direction):
    """All v2 edges are native, including external and per-edge unresolved endpoints."""
    if direction not in ('in', 'out', 'both'):
        raise ToolError('direction must be in, out or both')
    branches = []
    for side in (('out', 'in') if direction == 'both' else (direction,)):
        for label, identity in (('LCTNode', 'node_id:wanted'),
                                ('LCTBoundary', 'boundary_id:boundary_key')):
            prefix = ('UNWIND $ids AS wanted WITH wanted, '
                      "'external:' + wanted AS boundary_key ")
            anchor = f'({"a" if side == "out" else "b"}:{label} {{namespace:$namespace, version:$version, {identity}}})'
            if side == 'out':
                pattern = anchor + '-[r]->(b)'
            else:
                pattern = '(a)-[r]->' + anchor
            branches.append(prefix + 'MATCH ' + pattern +
                ' WHERE r.namespace=$namespace AND r.version=$version '
                'AND type(r) IN $allowed RETURN r.edge_id AS edge_id')
    return ('CALL () { ' + ' UNION '.join(branches) + ' } WITH DISTINCT edge_id '
            'MATCH (e:LCTEdge {namespace:$namespace, version:$version, edge_id:edge_id}) '
            'WHERE ($types IS NULL OR e.kind IN $types) AND '
            '($cursor IS NULL OR e.edge_id > $cursor) '
            'RETURN e.edge_id AS id, e.source_boundary_id AS source_boundary_id, '
            'e.target_boundary_id AS target_boundary_id, '
            'CASE WHEN size(e.raw_json)>65536 THEN null ELSE e.raw_json END AS raw, '
            'size(e.raw_json)>65536 AS raw_too_large ORDER BY id LIMIT $fetch')


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
            ("lct_boundary_scope", "LCTBoundary", "s.namespace, s.version, s.boundary_id"),
        ):
            session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (s:{label}) "
                        f"REQUIRE ({keys}) IS UNIQUE").consume()

    def maintain_indexes(self, legacy_edges=False):
        """Offline idempotent DDL; legacy endpoint indexes only aid old scopes."""
        with self.driver.session(database=self.database) as session:
            self._schema(session)
            if legacy_edges:
                for side in ("source", "target"):
                    session.run(
                        f"CREATE INDEX lct_edge_scope_{side} IF NOT EXISTS "
                        f"FOR (e:LCTEdge) ON (e.namespace, e.version, e.{side})"
                    ).consume()

    def migrate_projection(self, namespace, version, expected_fingerprint):
        """Offline, resumable in-place v1 -> v2 projection maintenance.

        Stop the query service first. Only derived boundary nodes, native relationships,
        and projection fields change; existing source nodes, raw edges and evidence stay.
        The marker stays incomplete on any failure, including an interrupted process.
        """
        scope = _scope(namespace, version)
        if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
            raise ToolError('Explicit snapshot fingerprint required')
        owner = uuid4().hex
        with self.driver.session(database=self.database, fetch_size=64) as session:
            self._schema(session)
            with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                row = tx.run(
                    'MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                    'SET s.lock_nonce=$nonce RETURN s.fingerprint AS fingerprint, '
                    's.complete AS complete, s.projection_schema AS schema, '
                    's.owner AS owner, s.lease_until AS lease, s.storage_format AS format',
                    **scope, nonce=uuid4().hex).single()
                if row is None or row['fingerprint'] != expected_fingerprint:
                    raise ToolError('Snapshot missing or fingerprint mismatch')
                if row['schema'] == PROJECTION_SCHEMA and row['complete'] is True:
                    return dict(**scope, fingerprint=expected_fingerprint, already_present=True)
                if row['schema'] not in (None, PROJECTION_SCHEMA):
                    raise ToolError('Unsupported projection schema')
                if row['format'] != 'chunks-v1':
                    raise ToolError('Migration requires chunks-v1 evidence layout')
                if row['owner'] is not None and row['lease'] is not None and row['lease'] >= time.time():
                    raise ToolError('Snapshot maintenance busy (active writer)')
                tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                       "SET s.complete=false, s.state='migrating', s.owner=$owner, "
                       's.lease_until=$lease', **scope, owner=owner,
                       lease=time.time()+LEASE_SECONDS).consume()
            try:
                # Full existing projection is the sole migration input. No SQLite/source parsing.
                nodes = [json.loads(r['raw']) for r in session.run(
                    'MATCH (n:LCTNode {namespace:$namespace, version:$version}) '
                    'RETURN n.raw_json AS raw ORDER BY n.node_id', **scope)]
                edges = [json.loads(r['raw']) for r in session.run(
                    'MATCH (e:LCTEdge {namespace:$namespace, version:$version}) '
                    'RETURN e.raw_json AS raw ORDER BY e.edge_id', **scope)]
                parts = list(session.run(
                    'MATCH (c:LCTChunk {namespace:$namespace, version:$version}) '
                    'RETURN c.kind AS kind, c.ordinal AS ordinal, c.data AS data '
                    'ORDER BY kind, ordinal', **scope))
                metadata = {}
                for kind in ('graph', 'source'):
                    selected = [r for r in parts if r['kind'] == kind]
                    if not selected or [r['ordinal'] for r in selected] != list(range(len(selected))):
                        raise ToolError('Snapshot evidence incomplete')
                    metadata[kind] = ''.join(r['data'] for r in selected)
                persisted_fingerprint = digest(_snapshot_payload(
                    nodes, edges, json.loads(metadata['graph']), json.loads(metadata['source'])))
                if persisted_fingerprint != expected_fingerprint:
                    raise ToolError('Persisted snapshot fingerprint mismatch')
                node_ids = {n['node_id'] for n in nodes}
                if len(node_ids) != len(nodes) or len({e['edge_id'] for e in edges}) != len(edges):
                    raise ToolError('Duplicate graph identity')
                if any(e.get('kind') not in REL_TYPES for e in edges):
                    raise ToolError('Unsupported relationship kind')
                boundary = _boundaries(edges, node_ids)
                for batch in _batches(boundary.values()):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row MERGE (b:LCTBoundary '
                           '{namespace:$namespace, version:$version, boundary_id:row.boundary_id}) '
                           'SET b.endpoint_id=row.endpoint_id, b.category=row.category, '
                           'b.lookup_repository=row.lookup_repository, b.lookup_module=row.lookup_module, '
                           'b.lookup_name=row.lookup_name, b.lookup_status=row.lookup_status, '
                           'b.lookup_reason=row.lookup_reason',
                           batch, state='migrating')
                for batch in _batches(dict(edge_id=e['edge_id'],
                                            source_boundary=_boundary_id(e,'source',node_ids),
                                            target_boundary=_boundary_id(e,'target',node_ids))
                                      for e in edges):
                    _write(session, scope, owner,
                           'UNWIND $rows AS row MATCH (e:LCTEdge '
                           '{namespace:$namespace, version:$version, edge_id:row.edge_id}) '
                           'SET e.source_boundary_id=row.source_boundary, '
                           'e.target_boundary_id=row.target_boundary', batch, state='migrating')
                for kind in sorted(REL_TYPES):
                    rows = (dict(edge_id=e['edge_id'], source=e.get('source'),
                                 target=e.get('target'),
                                 source_boundary=_boundary_id(e,'source',node_ids),
                                 target_boundary=_boundary_id(e,'target',node_ids))
                            for e in edges if e['kind'] == kind)
                    for batch in _batches(rows):
                        _write(session, scope, owner,
                               'UNWIND $rows AS row '
                               'OPTIONAL MATCH (an:LCTNode {namespace:$namespace, version:$version, node_id:row.source}) '
                               'OPTIONAL MATCH (ab:LCTBoundary {namespace:$namespace, version:$version, boundary_id:row.source_boundary}) '
                               'OPTIONAL MATCH (bn:LCTNode {namespace:$namespace, version:$version, node_id:row.target}) '
                               'OPTIONAL MATCH (bb:LCTBoundary {namespace:$namespace, version:$version, boundary_id:row.target_boundary}) '
                               'WITH row, coalesce(an,ab) AS a, coalesce(bn,bb) AS b '
                               f'MERGE (a)-[r:{kind} {{namespace:$namespace, version:$version, edge_id:row.edge_id}}]->(b) '
                               'SET r.source_boundary_id=row.source_boundary, '
                               'r.target_boundary_id=row.target_boundary', batch, state='migrating')
                with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                    _fence(tx, scope, owner, 'migrating')
                    tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                           "SET s.state='validating', s.native_count=$native, "
                           's.boundary_count=$boundary, s.projection_schema=$schema',
                           **scope, native=len(edges), boundary=len(boundary),
                           schema=PROJECTION_SCHEMA).consume()
                _verify(session, scope, owner, nodes, edges, node_ids, metadata)
                with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                    _fence(tx, scope, owner, 'validating')
                    tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                           "SET s.complete=true, s.state='complete', s.owner=null, "
                           's.lease_until=null', **scope).consume()
            except Exception:
                try:
                    with session.begin_transaction(timeout=IMPORT_TIMEOUT_SECONDS) as tx:
                        _fence(tx, scope, owner, None)
                        tx.run('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version}) '
                               "SET s.complete=false, s.state='failed', s.owner=null, "
                               's.lease_until=null', **scope).consume()
                except Exception:
                    pass
                raise
        return dict(**scope, fingerprint=expected_fingerprint, nodes=len(nodes),
                    edges=len(edges), boundaries=len(boundary), already_present=False)

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

    def snapshot_summary(self, namespace, version):
        """Marker-only status; complete evidence is available via snapshot_evidence."""
        fingerprint, rows = self._read(namespace, version,
            "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
            "RETURN s.node_count AS nodes, s.edge_count AS edges, "
            "s.native_count AS native_edges, s.chunk_count AS chunks, "
            "s.projection_schema AS projection_schema, "
            "s.graph_sha256 AS graph_sha256, s.source_sha256 AS source_sha256, "
            "s.source_fingerprint AS source_fingerprint, "
            "s.source_repository_count AS source_repository_count, "
            "s.storage_format AS storage_format")
        return dict(namespace=namespace, version=version, fingerprint=fingerprint,
                    **dict(rows[0]), storage_complete=True,
                    evidence_detail="Use snapshot_evidence for full graph/source JSON, including UNKNOWN reasons, analysis complete flags and repository revisions")

    def snapshot_evidence(self, namespace, version, kind, cursor=None):
        """Read a UTF-8 JSON fragment, without materializing either complete document."""
        if kind not in ('graph', 'source'):
            raise ToolError('kind must be graph or source')
        if cursor is None:
            ordinal, offset = 0, 0
        else:
            if not isinstance(cursor, str) or len(cursor) > 30:
                raise ToolError('Invalid evidence cursor')
            try:
                ordinal, offset = map(int, cursor.split(':'))
            except (ValueError, TypeError):
                raise ToolError('Invalid evidence cursor') from None
            if ordinal < 0 or offset < 0:
                raise ToolError('Invalid evidence cursor')
        _, marker = self._read(namespace, version,
            "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
            "RETURN s.storage_format AS format")
        if marker[0]['format'] == 'chunks-v1':
            _, rows = self._read(namespace, version,
                "MATCH (c:LCTChunk {namespace:$namespace, version:$version, kind:$kind}) "
                "WHERE c.ordinal >= $ordinal "
                "RETURN c.ordinal AS ordinal, substring(c.data, $offset, 8192) AS data, "
                "size(c.data) AS length ORDER BY ordinal LIMIT 2",
                kind=kind, ordinal=ordinal, offset=offset)
            if not rows or rows[0]['ordinal'] != ordinal or offset >= rows[0]['length']:
                raise ToolError('Invalid or incomplete evidence cursor')
            row = rows[0]
            end = offset + len(row['data'])
            more = end < row['length'] or len(rows) > 1
            next_cursor = (f'{ordinal}:{end}' if end < row['length'] else
                           f'{ordinal + 1}:0') if more else None
        else:
            if ordinal != 0:
                raise ToolError('Invalid evidence cursor')
            property_name = 'graph_json' if kind == 'graph' else 'source_json'
            _, rows = self._read(namespace, version,
                "MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) "
                f"RETURN substring(s.{property_name}, $offset, 8192) AS data, "
                f"size(s.{property_name}) AS length", offset=offset)
            row = rows[0]
            if row['length'] is None or offset >= row['length']:
                raise ToolError('Invalid evidence cursor')
            end = offset + len(row['data'])
            more = end < row['length']
            next_cursor = f'0:{end}' if more else None
        return dict(kind=kind, fragment=row['data'], format='JSON fragments',
                    has_more=more, next_cursor=next_cursor)

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

    def list_nodes(self, namespace, version, kind=None, repository=None, limit=100,
                   cursor=None):
        if kind is not None and kind not in NODE_LABELS:
            raise ToolError("Unsupported node kind")
        if repository is not None and not isinstance(repository, str):
            raise ToolError("repository must be a string")
        limit = _limit(limit)
        cursor = _after(cursor)
        _, rows = self._read(namespace, version,
            "MATCH (n:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE ($kind IS NULL OR n.kind=$kind) AND "
            "($repository IS NULL OR n.repository=$repository) AND "
            "($cursor IS NULL OR n.node_id > $cursor) "
            "RETURN n.node_id AS id, "
            "CASE WHEN size(n.raw_json)>65536 THEN null ELSE n.raw_json END AS raw "
            "ORDER BY id LIMIT $fetch",
            kind=kind, repository=repository, cursor=cursor,
            fetch=min(limit, PAGE_FETCH - 1) + 1)
        return _bounded_page(rows, 'nodes', limit, cursor)

    def get_nodes(self, namespace, version, ids):
        ids = _ids(ids)
        _, rows = self._read(namespace, version,
            "MATCH (n:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE n.node_id IN $ids RETURN n.node_id AS id, "
            "CASE WHEN size(n.raw_json)>65536 THEN null ELSE n.raw_json END AS raw", ids=ids)
        if any(row['raw'] is None for row in rows):
            raise ToolError('Single graph record exceeds reply byte limit')
        by_id = {row["id"]: json.loads(row["raw"]) for row in rows}
        result = [by_id[i] for i in ids if i in by_id]
        if len(canonical(result).encode('utf-8')) > MAX_REPLY_DATA_BYTES:
            raise ToolError('Node reply exceeds byte limit; use get_nodes_page')
        return result

    def get_nodes_page(self, namespace, version, ids, cursor=0):
        ids = _ids(ids)
        if type(cursor) is not int or cursor < 0 or cursor > len(ids):
            raise ToolError('Invalid requested-ID cursor')
        # The cursor is a position in the deduplicated requested IDs, including missing IDs.
        selected = ids[cursor:cursor + min(PAGE_FETCH - 1, len(ids) - cursor)]
        _, rows = self._read(namespace, version,
            "MATCH (n:LCTNode {namespace:$namespace, version:$version}) "
            "WHERE n.node_id IN $ids RETURN n.node_id AS id, "
            "CASE WHEN size(n.raw_json)>65536 THEN null ELSE n.raw_json END AS raw",
            ids=selected)
        by_id = {row['id']: row['raw'] for row in rows}
        items, consumed = [], 0
        for item_id in selected:
            if item_id in by_id:
                if by_id[item_id] is None:
                    if items:
                        break
                    raise ToolError('Single graph record exceeds reply byte limit')
                item = json.loads(by_id[item_id])
                trial = dict(nodes=[*items, item], has_more=True,
                             next_cursor=cursor + consumed + 1)
                if len(canonical(trial).encode('utf-8')) > MAX_REPLY_DATA_BYTES:
                    if not items:
                        raise ToolError('Single graph record exceeds reply byte limit')
                    break
                items.append(item)
            consumed += 1
        next_pos = cursor + consumed
        more = next_pos < len(ids)
        return dict(nodes=items, has_more=more, next_cursor=next_pos if more else None)

    def get_relations(self, namespace, version, ids, types=None, direction="both", limit=100,
                      cursor=None):
        ids = _ids(ids)
        if direction not in ("in", "out", "both"):
            raise ToolError("direction must be in, out or both")
        if types is not None and (not isinstance(types, (list, tuple)) or
                                  any(t not in REL_TYPES for t in types)):
            raise ToolError("Unsupported relationship type")
        limit = _limit(limit)
        cursor = _after(cursor)
        params = dict(ids=ids, types=list(types) if types is not None else None,
                      direction=direction, cursor=cursor,
                      fetch=min(limit, PAGE_FETCH - 1) + 1)
        native_query, external_query = relation_queries(direction)
        _, marker = self._read(namespace, version,
            'MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) '
            'RETURN s.projection_schema AS projection_schema')
        if marker[0]['projection_schema'] == PROJECTION_SCHEMA:
            _, rows = self._read(namespace, version, native_relation_query(direction),
                                 **params, allowed=sorted(REL_TYPES))
            return _bounded_page(rows, 'edges', limit, cursor)
        # Compatibility for immutable legacy projections; migrate by fresh namespace.
        _, internal = self._read(namespace, version, native_query,
                                 **params, allowed=sorted(REL_TYPES))
        _, external = self._read(namespace, version, external_query, **params)
        combined = {row['id']: row for row in [*internal, *external]}
        ordered = [combined[k] for k in sorted(combined)]
        return _bounded_page(ordered, 'edges', limit, cursor)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded Neo4j projection of a published LCT snapshot")
    parser.add_argument("--config", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import")
    maintenance = commands.add_parser("maintain-indexes")
    maintenance.add_argument("--legacy-edges", action="store_true")
    commands.add_parser("info")
    migration = commands.add_parser("migrate-projection")
    migration.add_argument("--expected-fingerprint", required=True)
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
            elif args.command == "maintain-indexes":
                graph.maintain_indexes(args.legacy_edges)
                result = {"database": args.database, "legacy_edge_indexes": args.legacy_edges}
            elif args.command == "migrate-projection":
                result = graph.migrate_projection(args.namespace, args.version,
                                                  args.expected_fingerprint)
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
