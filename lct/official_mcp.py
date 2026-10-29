"""Validated inputs for Neo4j's official read-cypher tool, not an MCP server.

The official server fixes the database; each statement additionally fixes the LCT
namespace and version. These filters are query semantics, not access control.
"""
import argparse

from .common import canonical
from .neo4j_graph import REL_TYPES, PAGE_FETCH, PROJECTION_SCHEMA, _after, _ids, _limit, _scope, native_relation_query


def read_cypher_requests(namespace, version, ids, expected_fingerprint, types=None,
                         direction='both', limit=100, cursor=None):
    scope = _scope(namespace, version)
    ids = _ids(ids)
    if types is not None and (not isinstance(types, (list, tuple)) or
                              any(t not in REL_TYPES for t in types)):
        from .common import ToolError
        raise ToolError('Unsupported relationship type')
    limit = _limit(limit)
    cursor = _after(cursor)
    from .common import ToolError
    if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64 or any(
            c not in '0123456789abcdef' for c in expected_fingerprint):
        raise ToolError('Explicit 64-character snapshot fingerprint required')
    params = dict(**scope, ids=ids, types=list(types) if types is not None else None,
                  cursor=cursor, fetch=min(limit, PAGE_FETCH - 1) + 1,
                  allowed=sorted(REL_TYPES), expected_fingerprint=expected_fingerprint,
                  projection_schema=PROJECTION_SCHEMA)
    guard = ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
             'projection_schema:$projection_schema, fingerprint:$expected_fingerprint}) ')
    marker = guard + 'RETURN s.fingerprint AS fingerprint, s.node_count AS nodes, '
    marker += 's.edge_count AS edges, s.boundary_count AS boundary_count'
    query = guard + 'WITH s ' + native_relation_query(direction).replace(
        'WITH DISTINCT edge_id', 'WITH DISTINCT s, edge_id').replace(
        'RETURN e.edge_id AS id,', 'RETURN s.fingerprint AS fingerprint, e.edge_id AS id,')
    # A missing marker is an error; do not interpret zero rows as an empty graph.
    return [dict(name='read-cypher', arguments=dict(query=marker, params=params)),
            dict(name='read-cypher', arguments=dict(query=query, params=params))]


def node_read_cypher_requests(namespace, version, ids, expected_fingerprint,
                              boundary=False):
    """Fetch known code nodes, or explicit physical boundary IDs returned by edge rows."""
    from .common import ToolError
    if boundary and any(not (i.startswith('external:') or i.startswith('unresolved:'))
                        for i in ids):
        raise ToolError('Boundary lookup requires physical boundary IDs')
    if len(_ids(ids)) > PAGE_FETCH - 1:
        raise ToolError('Node request supports at most 16 IDs; split into batches')
    requests = read_cypher_requests(namespace, version, ids, expected_fingerprint)
    params = requests[0]['arguments']['params']
    label = 'LCTBoundary' if boundary else 'LCTNode'
    key = 'boundary_id' if boundary else 'node_id'
    projection = ('n.boundary_id AS boundary_id, n.endpoint_id AS endpoint_id, '
                  'n.category AS category' if boundary else
                  'CASE WHEN size(n.raw_json)>65536 THEN null ELSE n.raw_json END AS raw, '
                  'size(n.raw_json)>65536 AS raw_too_large')
    guard = ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
             'projection_schema:$projection_schema, fingerprint:$expected_fingerprint}) ')
    query = (guard + 'WITH s UNWIND range(0, size($ids)-1) AS position '
             'WITH s, position, $ids[position] AS wanted '
             f'MATCH (n:{label} {{namespace:$namespace, version:$version, {key}:wanted}}) '
             'RETURN s.fingerprint AS fingerprint, ' + projection + ' ORDER BY position LIMIT $fetch')
    return [requests[0], dict(name='read-cypher', arguments=dict(query=query, params=params))]


def raw_fragment_requests(namespace, version, record_id, expected_fingerprint,
                          entity='edge', offset=0):
    """Bounded original raw JSON fragments for oversized edge or code-node rows."""
    from .common import ToolError
    if entity not in ('edge', 'node'):
        raise ToolError('fragment entity must be edge or node')
    if type(offset) is not int or offset < 0:
        raise ToolError('fragment offset must be a nonnegative integer')
    if len(_ids([record_id])) != 1:
        raise ToolError('Exactly one record ID required')
    requests = read_cypher_requests(namespace, version, [record_id],
                                    expected_fingerprint)
    params = dict(requests[0]['arguments']['params'], record_id=record_id, offset=offset)
    label, key = ('LCTEdge', 'edge_id') if entity == 'edge' else ('LCTNode', 'node_id')
    query = (
        'MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
        'projection_schema:$projection_schema, fingerprint:$expected_fingerprint}) '
        f'MATCH (record:{label} {{namespace:$namespace, version:$version, {key}:$record_id}}) '
        'RETURN s.fingerprint AS fingerprint, '
        'substring(record.raw_json,$offset,8192) AS fragment, '
        'size(record.raw_json) AS length')
    return [requests[0], dict(name='read-cypher', arguments=dict(query=query, params=params))]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Official Neo4j MCP read-cypher requests')
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--expected-fingerprint', required=True)
    parser.add_argument('--entity', choices=('relations', 'nodes', 'boundaries', 'edge-fragment', 'node-fragment'), default='relations')
    parser.add_argument('--direction', choices=('in', 'out', 'both'), default='both')
    parser.add_argument('--types', nargs='*', choices=sorted(REL_TYPES))
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--cursor')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('ids', nargs='+')
    args = parser.parse_args(argv)
    if args.entity == 'relations':
        requests = read_cypher_requests(args.namespace, args.version, args.ids,
            args.expected_fingerprint, args.types, args.direction, args.limit, args.cursor)
    elif args.entity in ('edge-fragment', 'node-fragment'):
        if len(args.ids) != 1:
            parser.error('fragment lookup requires exactly one ID')
        requests = raw_fragment_requests(args.namespace, args.version, args.ids[0],
            args.expected_fingerprint, entity=args.entity.split('-')[0], offset=args.offset)
    else:
        requests = node_read_cypher_requests(args.namespace, args.version, args.ids,
            args.expected_fingerprint, boundary=args.entity == 'boundaries')
    print(canonical(requests))


if __name__ == '__main__':
    main()
