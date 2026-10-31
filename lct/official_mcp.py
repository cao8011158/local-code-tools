"""Validated inputs for Neo4j's official read-cypher tool, not an MCP server.

The official server fixes the database; each statement additionally fixes the LCT
namespace and version. These filters are query semantics, not access control.
"""
import argparse

from .common import canonical
from .neo4j_graph import (REL_TYPES, VALUE_REL_TYPES, PAGE_FETCH, PROJECTION_SCHEMA,
                          VALUE_PROJECTION_SCHEMA, _after, _ids, _limit, _scope,
                          native_relation_query, value_relation_query)


def _schema(schema):
    from .common import ToolError
    if schema not in (PROJECTION_SCHEMA, VALUE_PROJECTION_SCHEMA):
        raise ToolError('Unsupported projection schema')
    return schema


def read_cypher_requests(namespace, version, ids, expected_fingerprint, types=None,
                         direction='both', limit=100, cursor=None,
                         projection_schema=PROJECTION_SCHEMA):
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
                  projection_schema=_schema(projection_schema))
    guard = ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
             'projection_schema:$projection_schema, fingerprint:$expected_fingerprint}) ')
    marker = guard + 'RETURN s.fingerprint AS fingerprint, s.node_count AS nodes, '
    marker += 's.edge_count AS edges, s.boundary_count AS boundary_count'
    query = guard + 'WITH s ' + native_relation_query(direction).replace(
        'CALL ()', 'CALL (s)').replace(
        'WITH DISTINCT edge_id', 'WITH DISTINCT s, edge_id').replace(
        'RETURN e.edge_id AS id,', 'RETURN s.fingerprint AS fingerprint, e.edge_id AS id,')
    # A missing marker is an error; do not interpret zero rows as an empty graph.
    return [dict(name='read-cypher', arguments=dict(query=marker, params=params)),
            dict(name='read-cypher', arguments=dict(query=query, params=params))]


def node_read_cypher_requests(namespace, version, ids, expected_fingerprint,
                              boundary=False, projection_schema=PROJECTION_SCHEMA):
    """Fetch known code nodes, or explicit physical boundary IDs returned by edge rows."""
    from .common import ToolError
    if boundary and any(not (i.startswith('external:') or i.startswith('unresolved:'))
                        for i in ids):
        raise ToolError('Boundary lookup requires physical boundary IDs')
    if len(_ids(ids)) > PAGE_FETCH - 1:
        raise ToolError('Node request supports at most 16 IDs; split into batches')
    requests = read_cypher_requests(namespace, version, ids, expected_fingerprint,
                                   projection_schema=projection_schema)
    params = requests[0]['arguments']['params']
    label = 'LCTBoundary' if boundary else 'LCTNode'
    key = 'boundary_id' if boundary else 'node_id'
    projection = ('n.boundary_id AS boundary_id, n.endpoint_id AS endpoint_id, '
                  'n.category AS category, n.lookup_repository AS lookup_repository, '
                  'n.lookup_module AS lookup_module, n.lookup_name AS lookup_name, '
                  'n.lookup_status AS lookup_status, n.lookup_reason AS lookup_reason' if boundary else
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
                          entity='edge', offset=0, projection_schema=PROJECTION_SCHEMA):
    """Bounded original raw JSON fragments for oversized edge or code-node rows."""
    from .common import ToolError
    if entity not in ('edge', 'node', 'value-edge', 'value-node'):
        raise ToolError('Unsupported fragment entity')
    if entity.startswith('value-') and projection_schema != VALUE_PROJECTION_SCHEMA:
        raise ToolError('Value fragments require v3 projection')
    if type(offset) is not int or offset < 0:
        raise ToolError('fragment offset must be a nonnegative integer')
    if len(_ids([record_id])) != 1:
        raise ToolError('Exactly one record ID required')
    requests = (value_read_cypher_requests(namespace, version, [record_id], expected_fingerprint)
                if entity.startswith('value-') else
                read_cypher_requests(namespace, version, [record_id], expected_fingerprint,
                                     projection_schema=projection_schema))
    params = dict(requests[0]['arguments']['params'], record_id=record_id, offset=offset)
    label, key = {'edge': ('LCTEdge', 'edge_id'), 'node': ('LCTNode', 'node_id'),
                  'value-edge': ('LCTValueEdge', 'value_edge_id'),
                  'value-node': ('LCTValue', 'value_id')}[entity]
    query = (
        'MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
        'projection_schema:$projection_schema, fingerprint:$expected_fingerprint' +
        (", value_projection:'complete'" if entity.startswith('value-') else '') + '}) '
        f'MATCH (record:{label} {{namespace:$namespace, version:$version, {key}:$record_id}}) '
        'RETURN s.fingerprint AS fingerprint, '
        'substring(record.raw_json,$offset,8192) AS fragment, '
        'size(record.raw_json) AS length')
    return [requests[0], dict(name='read-cypher', arguments=dict(query=query, params=params))]


def value_read_cypher_requests(namespace, version, ids, expected_fingerprint, types=None,
                               direction='both', limit=100, cursor=None):
    from .common import ToolError
    if types is not None and (not isinstance(types, (list, tuple)) or
                              any(t not in VALUE_REL_TYPES for t in types)):
        raise ToolError('Unsupported value relationship type')
    base = read_cypher_requests(namespace, version, ids, expected_fingerprint,
                                limit=limit, cursor=cursor,
                                projection_schema=VALUE_PROJECTION_SCHEMA)
    params = dict(base[0]['arguments']['params'],
                  types=list(types) if types is not None else None,
                  allowed=sorted(VALUE_REL_TYPES))
    guard = ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
             'projection_schema:$projection_schema, fingerprint:$expected_fingerprint, '
             "value_projection:'complete'}) ")
    marker = guard + ('RETURN s.fingerprint AS fingerprint, s.value_node_count AS value_nodes, '
                      's.value_edge_count AS value_edges, s.value_read_count AS value_reads')
    query = guard + 'WITH s ' + value_relation_query(direction).replace(
        'CALL ()', 'CALL (s)').replace(
        'WITH DISTINCT value_edge_id', 'WITH DISTINCT s, value_edge_id').replace(
        'RETURN e.value_edge_id AS id,',
        'RETURN s.fingerprint AS fingerprint, e.value_edge_id AS id,')
    return [dict(name='read-cypher', arguments=dict(query=marker, params=params)),
            dict(name='read-cypher', arguments=dict(query=query, params=params))]


def value_node_read_cypher_requests(namespace, version, ids, expected_fingerprint):
    from .common import ToolError
    if len(_ids(ids)) > PAGE_FETCH - 1:
        raise ToolError('Value node request supports at most 16 IDs')
    requests = value_read_cypher_requests(namespace, version, ids, expected_fingerprint)
    params = requests[0]['arguments']['params']
    guard = ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true, '
             'projection_schema:$projection_schema, fingerprint:$expected_fingerprint, '
             "value_projection:'complete'}) ")
    query = (guard + 'WITH s UNWIND range(0,size($ids)-1) AS position '
             'WITH s,position,$ids[position] AS wanted '
             'MATCH (n:LCTValue {namespace:$namespace, version:$version, value_id:wanted}) '
             'RETURN s.fingerprint AS fingerprint, '
             'CASE WHEN size(n.raw_json)>65536 THEN null ELSE n.raw_json END AS raw, '
             'size(n.raw_json)>65536 AS raw_too_large ORDER BY position LIMIT $fetch')
    return [requests[0], dict(name='read-cypher', arguments=dict(query=query, params=params))]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Official Neo4j MCP read-cypher requests')
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--expected-fingerprint', required=True)
    parser.add_argument('--entity', choices=('relations', 'nodes', 'boundaries', 'edge-fragment',
                                            'node-fragment', 'value-relations', 'value-nodes',
                                            'value-edge-fragment', 'value-node-fragment'),
                        default='relations')
    parser.add_argument('--projection-schema', choices=(PROJECTION_SCHEMA, VALUE_PROJECTION_SCHEMA),
                        default=PROJECTION_SCHEMA)
    parser.add_argument('--direction', choices=('in', 'out', 'both'), default='both')
    parser.add_argument('--types', nargs='*', choices=sorted(REL_TYPES | VALUE_REL_TYPES))
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--cursor')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('ids', nargs='+')
    args = parser.parse_args(argv)
    if args.entity == 'relations':
        requests = read_cypher_requests(args.namespace, args.version, args.ids,
            args.expected_fingerprint, args.types, args.direction, args.limit, args.cursor,
            args.projection_schema)
    elif args.entity == 'value-relations':
        requests = value_read_cypher_requests(args.namespace, args.version, args.ids,
            args.expected_fingerprint, args.types, args.direction, args.limit, args.cursor)
    elif args.entity in ('edge-fragment', 'node-fragment', 'value-edge-fragment', 'value-node-fragment'):
        if len(args.ids) != 1:
            parser.error('fragment lookup requires exactly one ID')
        requests = raw_fragment_requests(args.namespace, args.version, args.ids[0],
            args.expected_fingerprint, entity=args.entity.removesuffix('-fragment'),
            offset=args.offset, projection_schema=(VALUE_PROJECTION_SCHEMA if
            args.entity.startswith('value-') else args.projection_schema))
    elif args.entity == 'value-nodes':
        requests = value_node_read_cypher_requests(args.namespace, args.version, args.ids,
                                                    args.expected_fingerprint)
    else:
        requests = node_read_cypher_requests(args.namespace, args.version, args.ids,
            args.expected_fingerprint, boundary=args.entity == 'boundaries',
            projection_schema=args.projection_schema)
    print(canonical(requests))


if __name__ == '__main__':
    main()
