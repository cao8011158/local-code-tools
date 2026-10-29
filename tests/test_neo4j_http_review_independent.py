"""Independent HTTP auth, failure-redaction and lifecycle review probes."""
import asyncio
import json
import time

import httpx
import pytest
from mcp.server.auth.provider import AccessToken

import lct.neo4j_mcp as module
from lct.common import ToolError
from tests.test_neo4j_http_mcp import settings


RESOURCE = 'http://127.0.0.1:8765/mcp'
SECRET_MARKER = 'bolt://user:review-secret@private-host:7687'


class Verifier:
    async def verify_token(self, token):
        if token not in ('valid', 'expired'):
            return None
        return AccessToken(token=token, client_id='review', scopes=['graph:read'],
                           resource=RESOURCE, expires_at=int(time.time()) + (600 if token == 'valid' else -600))


class Backend:
    instances = []
    fail_start = False
    missing_start = False

    def __init__(self, *args):
        self.closed = False
        self.__class__.instances.append(self)

    fingerprint_calls = 0
    status_calls = 0

    def snapshot_fingerprint(self, namespace, version):
        self.fingerprint_calls += 1
        if self.fail_start:
            raise RuntimeError(SECRET_MARKER)
        if self.missing_start:
            raise ToolError('Neo4j snapshot missing or incomplete')
        return 'review-fingerprint'

    def snapshot_summary(self, namespace, version):
        self.status_calls += 1
        return {'fingerprint': 'review-fingerprint', 'nodes': 0, 'edges': 0,
                'storage_complete': True}

    def list_nodes(self, *args):
        raise RuntimeError(SECRET_MARKER)

    def close(self):
        self.closed = True


def app(monkeypatch):
    monkeypatch.setattr(module, 'Neo4jGraph', Backend)
    return module.create_app(uri='bolt://127.0.0.1:1', user='review', password='not-real',
                             database='neo4j', namespace='fixed-ns', version='fixed-v',
                             token_verifier=Verifier(), auth=settings(RESOURCE),
                             allowed_host='127.0.0.1:8765', allowed_origin='http://127.0.0.1:8765')


def test_start_failure_redacted_and_driver_closed(monkeypatch):
    monkeypatch.setattr(Backend, 'fail_start', True)
    application = app(monkeypatch)

    async def run():
        with pytest.raises(RuntimeError, match='^Graph snapshot unavailable$') as error:
            async with application.router.lifespan_context(application):
                pytest.fail('unavailable snapshot served')
        assert SECRET_MARKER not in str(error.value)
        assert Backend.instances[-1].closed

    asyncio.run(run())


def test_missing_or_incomplete_snapshot_closes_driver(monkeypatch):
    monkeypatch.setattr(Backend, 'missing_start', True)
    application = app(monkeypatch)

    async def run():
        with pytest.raises(RuntimeError, match='^Graph snapshot unavailable$'):
            async with application.router.lifespan_context(application):
                pytest.fail('missing or incomplete snapshot served')
        backend = Backend.instances[-1]
        assert backend.closed
        assert (backend.fingerprint_calls, backend.status_calls) == (1, 0)

    asyncio.run(run())


def test_expiry_discovery_redaction_and_normal_shutdown(monkeypatch):
    application = app(monkeypatch)

    async def run():
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8765') as client:
                denied = await client.post('/mcp', headers={'Authorization': 'Bearer expired'}, json={})
                assert denied.status_code == 401
                assert 'resource_metadata=' in denied.headers['www-authenticate']
                metadata = await client.get('/.well-known/oauth-protected-resource/mcp')
                assert metadata.status_code == 200
                assert metadata.json()['resource'] == RESOURCE
                assert 'graph:read' in metadata.json()['scopes_supported']
                headers = {'Authorization': 'Bearer valid', 'Accept': 'application/json, text/event-stream',
                           'MCP-Protocol-Version': '2025-11-25'}
                response = await client.post('/mcp', headers=headers, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'list_nodes', 'arguments': {}}})
                assert response.status_code == 200, response.text
                assert response.json()['result']['isError'] is True
                assert 'Graph read unavailable' in response.text
                assert SECRET_MARKER not in response.text
                assert 'review-secret' not in response.text
        assert Backend.instances[-1].closed

    asyncio.run(run())


def test_startup_reads_only_fingerprint_and_status_reads_summary(monkeypatch):
    application = app(monkeypatch)

    async def run():
        async with application.router.lifespan_context(application):
            backend = Backend.instances[-1]
            assert (backend.fingerprint_calls, backend.status_calls) == (1, 0)
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8765') as client:
                response = await client.post('/mcp', headers={
                    'Authorization': 'Bearer valid', 'Accept': 'application/json, text/event-stream',
                    'MCP-Protocol-Version': '2025-11-25'}, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'graph_status', 'arguments': {}}})
                assert response.status_code == 200, response.text
                result = response.json()['result']
                payload = result.get('structuredContent') or json.loads(result['content'][0]['text'])
                assert payload['fingerprint'] == 'review-fingerprint'
                assert payload['data']['storage_complete'] is True
            assert (backend.fingerprint_calls, backend.status_calls) == (1, 1)
        assert backend.closed

    asyncio.run(run())


def test_wrapped_reply_has_a_byte_ceiling_and_oversize_error(monkeypatch):
    class LargeBackend(Backend):
        def list_nodes(self, namespace, version, kind=None, repository=None, limit=100,
                       cursor=None):
            from lct.neo4j_graph import _bounded_page
            rows = [dict(id=f'{i:03}', raw=json.dumps({'node_id': f'{i:03}',
                                                        'evidence': '界\\' * 3500}))
                    for i in range(20)]
            rows = [row for row in rows if cursor is None or row['id'] > cursor]
            return _bounded_page(rows[:min(limit, 16) + 1], 'nodes', limit)

    monkeypatch.setattr(module, 'Neo4jGraph', LargeBackend)
    application = module.create_app(
        uri='bolt://127.0.0.1:1', user='review', password='not-real', database='neo4j',
        namespace='fixed-ns', version='fixed-v', token_verifier=Verifier(),
        auth=settings(RESOURCE), allowed_host='127.0.0.1:8765',
        allowed_origin='http://127.0.0.1:8765')

    async def run():
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                         base_url='http://127.0.0.1:8765') as client:
                cursor, seen = None, []
                while True:
                    response = await client.post('/mcp', headers={
                        'Authorization': 'Bearer valid',
                        'Accept': 'application/json, text/event-stream',
                        'MCP-Protocol-Version': '2025-11-25'}, json={
                        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': 'list_nodes', 'arguments': {'cursor': cursor}}})
                    assert response.status_code == 200
                    assert len(response.content) < 256 * 1024
                    result = response.json()['result']
                    assert not result.get('isError'), result
                    payload = result.get('structuredContent') or json.loads(result['content'][0]['text'])
                    data = payload['data']
                    seen.extend(n['node_id'] for n in data['nodes'])
                    if not data['has_more']:
                        break
                    cursor = data['next_cursor']
                assert seen == [f'{i:03}' for i in range(20)]

    asyncio.run(run())
