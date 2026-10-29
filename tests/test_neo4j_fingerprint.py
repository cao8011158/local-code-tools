"""Bounded startup marker read, independent of the full status metadata path."""

import pytest

from lct.common import ToolError
from lct.neo4j_graph import Neo4jGraph


class Result:
    def __init__(self, row):
        self.row = row

    def single(self):
        return self.row


class Session:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **params):
        self.calls.append((query, params))
        return Result(self.row)


class Driver:
    def __init__(self, row):
        self.session_instance = Session(row)
        self.options = []

    def session(self, **options):
        self.options.append(options)
        return self.session_instance


@pytest.mark.parametrize('row, expected', [
    ({'fingerprint': 'abc123'}, 'abc123'),
    (None, None),
    ({'fingerprint': None}, None),
])
def test_fingerprint_one_scoped_marker_query(row, expected):
    graph = Neo4jGraph.__new__(Neo4jGraph)
    graph.database = 'fixed-db'
    graph.driver = Driver(row)
    graph._read = lambda *args, **kwargs: pytest.fail('redundant _read invoked')
    graph.snapshot_info = lambda *args: pytest.fail('full metadata loaded')

    if expected is None:
        with pytest.raises(ToolError, match='missing or incomplete'):
            graph.snapshot_fingerprint('fixed-ns', 'fixed-v')
    else:
        assert graph.snapshot_fingerprint('fixed-ns', 'fixed-v') == expected

    assert graph.driver.options == [dict(database='fixed-db', default_access_mode='READ',
                                         fetch_size=64)]
    [(query, params)] = graph.driver.session_instance.calls
    assert query == ('MATCH (s:LCTSnapshot {namespace:$namespace, version:$version, complete:true}) '
                     'RETURN s.fingerprint AS fingerprint')
    assert params == {'namespace': 'fixed-ns', 'version': 'fixed-v'}


@pytest.mark.parametrize('namespace, version', [('', 'v'), ('ns', ''), (None, 'v')])
def test_fingerprint_invalid_scope_never_queries(namespace, version):
    graph = Neo4jGraph.__new__(Neo4jGraph)
    graph.database = 'fixed-db'
    graph.driver = Driver({'fingerprint': 'abc123'})
    with pytest.raises(ToolError):
        graph.snapshot_fingerprint(namespace, version)
    assert graph.driver.options == []
