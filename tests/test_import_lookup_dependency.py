"""Captured missing-import namespace is a durable reverse dependency, not a call."""

import json
import sqlite3

from lct.extract import python_nodes
from lct.graph import Graph
from lct.neo4j_graph import _boundaries, _boundary_id, native_relation_query
from lct.query import Query
from lct.storage import DDL
from tests.test_core import file


def build(files, repos=None):
    nodes, asts = [], {}
    for source in files:
        ns, trees = python_nodes(source)
        nodes.extend(ns)
        asts.update(trees)
    repos = repos or [dict(name='demo', path='.', head='x', status='', closed_world=True)]
    edges, _ = Graph(nodes, asts, repos).build()
    return nodes, edges


def lookup_edges(edges):
    imports = [e for e in edges if e['kind'] == 'IMPORTS']
    return imports, [e for e in edges if e['kind'] == 'LOOKUP_IN']


def test_missing_to_success_and_back_preserves_named_identity():
    caller = file('from helper import new_handler as alias\n', 'src/caller.py')
    old = file('def old(): pass\n', 'src/helper.py')
    nodes, edges = build([caller, old])
    imports, lookups = lookup_edges(edges)
    assert len(imports) == len(lookups) == 1
    pending, dependency = imports[0], lookups[0]
    assert pending['status'] == 'unresolved' and pending['unknown_origin'] is True
    assert pending['unresolved_reasons'] == ['jedi-no-result']
    assert pending['target'] == dependency['source']
    assert dependency['target'] == next(n['node_id'] for n in nodes if n['kind'] == 'module' and n['qualname'] == 'helper')
    assert pending['lookup'] == dict(repository='demo', module='helper', name='new_handler')
    assert not any(e['kind'] == 'CALLS' for e in edges)

    added = file('def new_handler(): pass\n', 'src/helper.py')
    resolved_nodes, resolved_edges = build([caller, added])
    imports, lookups = lookup_edges(resolved_edges)
    assert not lookups
    assert len(imports) == 1 and imports[0]['status'] == 'resolved'
    assert imports[0]['target'] == next(n['node_id'] for n in resolved_nodes if n['kind'] == 'function')
    _, missing_again = build([caller, old])
    assert lookup_edges(missing_again)[0][0]['target'] == pending['target']


def test_relative_lookup_and_distinct_repositories():
    sources = [file('from .helper import fresh as alias\n', 'src/pkg/caller.py'),
               file('def old(): pass\n', 'src/pkg/helper.py'),
               file('from pkg.helper import fresh\n', 'src/other.py', 'another'),
               file('def old(): pass\n', 'src/pkg/helper.py', 'another')]
    repos = [dict(name=name, path='.', head='x', status='', closed_world=True) for name in ('demo', 'another')]
    _, edges = build(sources, repos)
    imports, lookups = lookup_edges(edges)
    assert len(imports) == len(lookups) == 2
    assert len({e['target'] for e in imports}) == 2
    assert {e['lookup']['repository'] for e in imports} == {'demo', 'another'}


def test_shared_missing_name_and_ambiguous_module_do_not_guess():
    files = [file('from helper import fresh as first\n', 'src/a.py'),
             file('from helper import fresh as second\n', 'src/b.py'),
             file('def old(): pass\n', 'src/helper.py')]
    _, edges = build(files)
    imports, lookups = lookup_edges(edges)
    assert len(imports) == 2 and len(lookups) == 1
    assert {e['target'] for e in imports} == {lookups[0]['source']}

    duplicate = file('def other(): pass\n', 'packages/other/src/helper.py')
    _, edges = build(files + [duplicate])
    imports, lookups = lookup_edges(edges)
    assert not lookups
    assert all(e['target'] is None for e in imports)


def test_package_submodule_name_is_not_claimed_missing():
    files = [file('from pkg import child\n', 'src/caller.py'),
             file('\n', 'src/pkg/__init__.py'),
             file('x = 1\n', 'src/pkg/child.py')]
    _, edges = build(files)
    assert not lookup_edges(edges)[1]


def test_uncaptured_and_unpinned_module_keep_original_unknown(tmp_path):
    unowned, edges = build([file('from external import fresh\n')])
    assert not lookup_edges(edges)[1]
    assert lookup_edges(edges)[0][0]['target'] is None
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="old"}')
    sources = [file('from dnd5e_engine.evaluation import fresh\n', repo='sm'),
               file('def old(): pass\n', 'src/dnd5e_engine/evaluation.py', 'trpg-rules-engine')]
    repos = [dict(name='sm', path=str(tmp_path), head='sm', status=''),
             dict(name='trpg-rules-engine', path='none', head='new', status='')]
    _, edges = build(sources, repos)
    assert not lookup_edges(edges)[1]
    assert all(not e.get('lookup') for e in edges)


def test_matching_cross_repository_pin_can_locate_missing_name(tmp_path):
    import subprocess

    target = tmp_path / 'target'
    target.mkdir()
    (target / 'module.py').write_text('def old(): pass\n')
    for args in (('init',), ('config', 'user.name', 'Fixture'),
                 ('config', 'user.email', 'fixture@example.invalid'),
                 ('add', 'module.py'), ('-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')):
        subprocess.run(['git', *args], cwd=target, check=True, capture_output=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=target, check=True,
                          capture_output=True, text=True).stdout.strip()
    consumer = tmp_path / 'consumer'
    consumer.mkdir()
    (consumer / 'pyproject.toml').write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="' + head + '"}')
    files = [file('from dnd5e_engine.evaluation import fresh\n', repo='sm'),
             file('def old(): pass\n', 'src/dnd5e_engine/evaluation.py', 'trpg-rules-engine')]
    repos = [dict(name='sm', path=str(consumer), head='sm', status=''),
             dict(name='trpg-rules-engine', path=str(target), head=head, status='')]
    _, edges = build(files, repos)
    imports, lookups = lookup_edges(edges)
    assert len(imports) == len(lookups) == 1
    assert imports[0]['lookup'] == dict(repository='trpg-rules-engine',
                                       module='dnd5e_engine.evaluation', name='fresh')


def test_sqlite_reverse_traversal_is_indexed_and_projects_named_boundary(tmp_path):
    nodes, edges = build([file('from helper import fresh\n', 'src/caller.py'),
                          file('def old(): pass\n', 'src/helper.py')])
    imports, lookups = lookup_edges(edges)
    db = sqlite3.connect(':memory:')
    db.executescript(DDL)
    for e in edges:
        db.execute('insert into edges values(?,?,?,?,?,?)',
                   (e['edge_id'], e['source'], e['target'], e['kind'], e['status'], json.dumps(e)))
    module = lookups[0]['target']
    plan = db.execute('explain query plan select data from edges where target=? and kind in (?,?) order by edge_id limit ?',
                      (module, 'IMPORTS', 'LOOKUP_IN', 201)).fetchall()
    assert any('edge_target' in str(row) for row in plan)
    class LocalQuery(Query):
        def snapshot(self, version=None):
            return tmp_path, {'version': 'synthetic'}
        def db(self, folder):
            from contextlib import nullcontext
            return nullcontext(db)
        def freshness(self, version):
            return {}
    result = LocalQuery.__new__(LocalQuery).get_relations([module], direction='in', depth=2,
                        relation_types=['LOOKUP_IN', 'IMPORTS'])
    assert {e['edge_id'] for e in result['edges']} == {imports[0]['edge_id'], lookups[0]['edge_id']}
    boundary = _boundaries(edges, {n['node_id'] for n in nodes})
    record = boundary[_boundary_id(imports[0], 'target', {n['node_id'] for n in nodes})]
    assert record['category'] == 'unresolved'
    assert (record['lookup_module'], record['lookup_name']) == ('helper', 'fresh')
    assert 'LCTBoundary' in native_relation_query('in') and 'LCTBoundary' in native_relation_query('out')


def test_real_neo4j_lookup_projection_and_reverse_relation():
    import os
    import uuid

    import pytest

    from lct.common import canonical, digest
    from lct.neo4j_graph import Neo4jGraph
    from lct.official_mcp import node_read_cypher_requests

    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('owned Neo4j URI required')
    nodes, edges = build([file('from helper import fresh as f\n', 'src/caller.py'),
                          file('def old(): pass\n', 'src/helper.py')])
    imports, lookups = lookup_edges(edges)
    snapshot = dict(version='fixture-v1', nodes=nodes, edges=edges,
                    graph={'sites': []}, source={'repositories': []})
    snapshot['fingerprint'] = digest(canonical({k: snapshot[k] for k in
                                                ('nodes', 'edges', 'graph', 'source')}))
    namespace, version = 'lookup-test-' + uuid.uuid4().hex, 'fixture-v1'
    password = os.getenv('LCT_TEST_NEO4J_PASSWORD', 'synthetic-lct-batch1-only')
    with Neo4jGraph(uri, os.getenv('LCT_TEST_NEO4J_USER', 'neo4j'), password,
                    os.getenv('LCT_TEST_NEO4J_DATABASE', 'neo4j')) as graph:
        graph.maintain_indexes()
        graph.import_snapshot(namespace, version, snapshot)
        assert graph.import_snapshot(namespace, version, snapshot)['already_present']
        module = lookups[0]['target']
        assert graph.get_relations(namespace, version, [module], ['LOOKUP_IN'], 'in')['edges'] == lookups
        boundary = _boundary_id(imports[0], 'target', {n['node_id'] for n in nodes})
        assert graph.get_relations(namespace, version, [imports[0]['target']], ['IMPORTS'], 'in')['edges'] == imports
        request = node_read_cypher_requests(namespace, version, [boundary],
                                            snapshot['fingerprint'], boundary=True)[1]
        with graph.driver.session(database=graph.database) as session:
            row = session.run(request['arguments']['query'],
                              **request['arguments']['params']).single()
            assert row['category'] == 'unresolved'
            assert row['lookup_repository'] == 'demo'
            assert row['lookup_module'] == 'helper'
            assert row['lookup_name'] == 'fresh'
            assert row['lookup_status'] == 'unresolved'
            assert row['lookup_reason'] == 'named-import-unresolved'
            plan = session.run('EXPLAIN ' + request['arguments']['query'],
                               **request['arguments']['params']).consume().plan
            assert plan is not None
            def operators(item):
                return [item['operatorType'], *(op for child in item.get('children', []) for op in operators(child))]
            assert any('NodeUniqueIndexSeek' in op or 'NodeIndexSeek' in op
                       for op in operators(plan))
