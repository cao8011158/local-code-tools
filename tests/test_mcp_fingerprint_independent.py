"""Independent native marker-only startup checks; no graph metadata exists."""
import asyncio
import os
from uuid import uuid4

import pytest

from lct.common import ToolError
from lct.neo4j_graph import Neo4jGraph
from lct.neo4j_mcp import create_app
from tests.test_neo4j_http_mcp import LocalTestVerifier, settings


def connection():
    uri = os.getenv('LCT_TEST_NEO4J_URI')
    if not uri:
        pytest.skip('owned Neo4j required')
    return dict(uri=uri, user=os.getenv('LCT_TEST_NEO4J_USER', 'neo4j'),
                password=os.getenv('LCT_TEST_NEO4J_PASSWORD', 'synthetic-lct-batch1-only'),
                database=os.getenv('LCT_TEST_NEO4J_DATABASE', 'neo4j'))


def test_native_complete_marker_without_metadata_can_start(monkeypatch):
    kw = connection()
    ns = 'fingerprint-only-' + uuid4().hex
    with Neo4jGraph(**kw) as db:
        with db.driver.session(database=db.database) as s:
            db._schema(s)
            s.run('CREATE (:LCTSnapshot {namespace:$ns,version:"v",complete:true, '
                  'fingerprint:"fixed-fingerprint"})', ns=ns).consume()
        assert db.snapshot_fingerprint(ns, 'v') == 'fixed-fingerprint'
    def forbidden(*args, **kwargs):
        raise AssertionError('startup requested full metadata')
    monkeypatch.setattr(Neo4jGraph, 'snapshot_info', forbidden)
    resource = 'http://127.0.0.1:8765/mcp'
    app = create_app(**kw, namespace=ns, version='v',
                     token_verifier=LocalTestVerifier(resource), auth=settings(resource),
                     allowed_host='127.0.0.1:8765', allowed_origin='http://127.0.0.1:8765')
    async def run():
        async with app.router.lifespan_context(app):
            pass
    asyncio.run(run())


def test_native_incomplete_and_wrong_scope_are_rejected():
    kw = connection()
    ns = 'fingerprint-hidden-' + uuid4().hex
    with Neo4jGraph(**kw) as db:
        with db.driver.session(database=db.database) as s:
            db._schema(s)
            s.run('CREATE (:LCTSnapshot {namespace:$ns,version:"v",complete:false, '
                  'fingerprint:"hidden"})', ns=ns).consume()
        for namespace, version in ((ns, 'v'), (ns, 'missing'), (ns+'other', 'v')):
            with pytest.raises(ToolError):
                db.snapshot_fingerprint(namespace, version)
