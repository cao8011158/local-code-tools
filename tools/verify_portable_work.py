"""Independent offline small-graph package and restored Work/MCP acceptance.

Synthetic vectors test mechanics only, never retrieval quality or provider output.
Prepare with the reviewed tool; restore the downloaded ZIP with that tool; verify
in a separate process using only the restored tool's Python modules.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import zipfile


QUERIES = [('module', 'workflow'), ('class', 'Parcel'), ('function', 'dispatch_parcel')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def result_ids(result):
    return [x['node_id'] for x in result['results']]


def prepare(root, output):
    from tests.test_small_graph_mcp_e2e import prepare as fixture
    from tests.synthetic_support import deterministic_vector, forbid_provider
    from lct.common import atomic, config, inventory
    from lct.embedding import Embeddings, vector_key
    from lct.extract import extract, embedding_texts
    from lct.management import backup
    from lct.neo4j_graph import load_snapshot
    from lct.query import Query
    from lct.storage import build

    output.mkdir(parents=True, exist_ok=False)
    source, config_path, _ = fixture(output)
    raw = json.loads(config_path.read_text())
    raw['synthetic_fixture_notice'] = 'SYNTHETIC VECTORS ONLY; no provider API or retrieval-quality claim'
    atomic(config_path, raw)
    c = config(config_path)
    files, _, _ = inventory(c)
    nodes, _ = extract(files)
    texts = embedding_texts(nodes, files)
    cache = Embeddings(c)
    try:
        for kind, values in [('document', [x['text'] for x in texts]),
                             ('query', [q for _, q in QUERIES])]:
            for value in values:
                cache.db.execute('insert or ignore into vectors values(?,?,?,?,?)',
                                 (vector_key(c['embedding'], value, kind), kind,
                                  deterministic_vector(value).tobytes(), 'SYNTHETIC-TEST-ONLY', 0))
        cache.db.commit()
    finally:
        cache.close()
    with forbid_provider():
        m = build(c, offline=True)
        graph = load_snapshot(c, m['version'])
        assert (len(graph['nodes']), len(graph['edges'])) == (17, 30)
        q = Query(c)
        expected = {}
        for level, text in QUERIES:
            for mode in ('bm25', 'dense', 'rrf'):
                rows = q.search_code(text, level=level, mode=mode, limit=50)
                assert rows['results']
                expected[level + ':' + mode] = result_ids(rows)
        docs = q.search_docs('amberquartz', limit=50)
        assert docs['results']
        ids = [n['node_id'] for n in graph['nodes']]
        sources = q.get_nodes(ids, max_bytes=200000)['nodes']
        for n in sources:
            n.pop('live_file_matches', None)
        data = backup(c)
    bundle = output / 'small-graph-synthetic.zip'
    shutil.copyfile(data['archive'], bundle)
    proof = dict(graph=graph, searches=expected, doc_ids=result_ids(docs), sources=sources,
                 artifacts=m['artifacts'], original_source=str(source), original_data=c['data'],
                 version=m['version'], program_hash=m['program_hash'],
                 archive_sha256=sha(bundle), archive_bytes=bundle.stat().st_size,
                 embedding_requests=m['embedding_run']['requests'], synthetic=True)
    assert proof['embedding_requests'] == 0
    (output / 'expected.json').write_text(json.dumps(proof, indent=2))
    # Make only this command's owned fixture locations unavailable; retain them for diagnosis.
    source.rename(output / 'source-unavailable')
    Path(c['data']).rename(output / 'data-unavailable')
    print(json.dumps({k: proof[k] for k in ('version', 'archive_sha256', 'archive_bytes',
                                           'embedding_requests', 'synthetic')}))


def restore(archive, destination, expected):
    from lct.management import restore as restore_archive
    proof = json.loads(expected.read_text())
    assert sha(archive) == proof['archive_sha256'], 'Downloaded archive differs'
    assert not Path(proof['original_source']).exists()
    assert not Path(proof['original_data']).exists()
    # This is data parsing only. restore() independently verifies membership,
    # checksums, the archived config identity and all index artifacts before use.
    with zipfile.ZipFile(archive) as bundle:
        source_config = json.loads(bundle.read('config.json'))
    result = restore_archive(source_config, archive, destination)
    print(json.dumps(result))


def verify(root, expected):
    import lct.common as common
    from lct.common import config
    from lct.neo4j_graph import Neo4jGraph, load_snapshot
    from lct.query import Query
    from lct.storage import manifest
    from tests.synthetic_support import forbid_provider

    assert common.ROOT.resolve() == root.resolve(), 'Wrong toolkit imported'
    proof = json.loads(expected.read_text())
    assert not Path(proof['original_source']).exists()
    assert not Path(proof['original_data']).exists()
    c = config(root / 'config.json')
    assert Path(c['data']) == root / 'data'
    folder, m = manifest(c)
    assert m['version'] == proof['version'] and m['program_hash'] == proof['program_hash']
    assert m['artifacts'] == proof['artifacts']
    for name, value in proof['artifacts'].items():
        assert sha(folder / name) == value, name
    snapshot = load_snapshot(c, m['version'])
    assert snapshot == proof['graph'], 'Graph/source/UNKNOWN identity changed'
    q = Query(c)
    with forbid_provider():
        for level, text in QUERIES:
            for mode in ('bm25', 'dense', 'rrf'):
                assert result_ids(q.search_code(text, level=level, mode=mode, limit=50)) == proof['searches'][level+':'+mode]
            assert result_ids(q.search_code(text, level=level, mode='dense', exact=True, limit=50)) == proof['searches'][level+':dense']
        assert result_ids(q.search_docs('amberquartz', limit=50)) == proof['doc_ids']
        nodes = q.get_nodes([n['node_id'] for n in snapshot['nodes']], max_bytes=200000)['nodes']
        for n in nodes:
            assert n.pop('live_file_matches') is False
        assert nodes == proof['sources']

    async def decode(session, name, args=None):
        result = await session.call_tool(name, args or {})
        assert not result.isError, result.content
        return result.structuredContent or json.loads(next(x.text for x in result.content if x.type == 'text'))

    async def stdio():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client, get_default_environment
        env = get_default_environment()
        env.update(VOYAGE_API_KEY='', LCT_CONFIG=str(root / 'config.json'), PYTHONDONTWRITEBYTECODE='1')
        params = StdioServerParameters(command=sys.executable,
                args=[str(root / 'local_code_tools.py'), '--config', str(root / 'config.json'), 'mcp'],
                cwd=str(root), env=env)
        with (root / 'acceptance-stdio.log').open('w') as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert {x.name for x in (await session.list_tools()).tools} == {'index_status', 'search_code', 'search_docs', 'get_nodes', 'get_relations'}
                    status = await decode(session, 'index_status')
                    assert status['version'] == proof['version'] and status['dense_ready']
                    for level, text in QUERIES:
                        for mode in ('bm25', 'dense', 'rrf'):
                            found = await decode(session, 'search_code', dict(query=text, level=level, mode=mode, limit=50))
                            assert result_ids(found) == proof['searches'][level+':'+mode]
                    assert result_ids(await decode(session, 'search_docs', dict(query='amberquartz', limit=50))) == proof['doc_ids']
                    ids = [n['node_id'] for n in snapshot['nodes']]
                    restored = await decode(session, 'get_nodes', dict(node_ids=ids, max_bytes=200000))
                    for n in restored['nodes']:
                        assert n.pop('live_file_matches') is False
                    assert restored['nodes'] == proof['sources']
                    calls = await decode(session, 'get_relations', dict(node_ids=ids, relation_types=['CALLS'], direction='both'))
                    assert calls['version'] == proof['version'] and calls['edges']

    uri = os.environ['LCT_TEST_NEO4J_URI']
    user = os.environ['LCT_TEST_NEO4J_USER']
    password = os.environ['LCT_TEST_NEO4J_PASSWORD']
    database = os.environ['LCT_TEST_NEO4J_DATABASE']
    namespace = 'restore-acceptance-' + m['version']
    with Neo4jGraph(uri, user, password, database) as graph:
        imported = graph.import_snapshot(namespace, m['version'], snapshot)
        assert (imported['nodes'], imported['edges']) == (17, 30)

    async def http():
        import uvicorn
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        from lct.neo4j_mcp import create_app
        from tests.test_neo4j_http_mcp import LocalTestVerifier, settings
        # Test verifier and loopback transport only; no public server is published.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        resource = base + '/mcp'
        app = create_app(uri=uri, user=user, password=password, database=database,
                         namespace=namespace, version=m['version'], token_verifier=LocalTestVerifier(resource),
                         auth=settings(resource), allowed_host=f'127.0.0.1:{port}', allowed_origin=base)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                if task.done():
                    await task
                await asyncio.sleep(.05)
            assert server.started
            async with streamablehttp_client(resource, headers={'Authorization':'Bearer local-full', 'Origin':base}) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert {x.name for x in (await session.list_tools()).tools} == {'graph_status', 'list_nodes', 'get_nodes', 'get_relations'}
                    async def call(name, args=None):
                        value = await decode(session, name, args)
                        assert (value['namespace'], value['version'], value['fingerprint']) == (namespace, m['version'], snapshot['fingerprint'])
                        return value['data']
                    status = await call('graph_status')
                    assert (status['nodes'], status['edges']) == (17, 30)
                    assert status['graph'] == snapshot['graph'] and status['source'] == snapshot['source']
                    for kind in ('module', 'class', 'function'):
                        got = await call('list_nodes', dict(kind=kind, limit=500))
                        assert got['nodes'] == [n for n in snapshot['nodes'] if n['kind']==kind]
                    ids = [n['node_id'] for n in snapshot['nodes']]
                    assert await call('get_nodes', dict(ids=ids)) == snapshot['nodes']
                    edges = await call('get_relations', dict(ids=ids, direction='both', limit=5000))
                    assert edges == dict(edges=snapshot['edges'], has_more=False)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 15)

    asyncio.run(stdio())
    asyncio.run(http())
    print(json.dumps(dict(status='PASS', nodes=17, edges=30, source_missing=True,
                          graph_identity_preserved=True, index_artifacts_unchanged=True,
                          lexical_dense_rrf_preserved=True, stdio_tools=5, http_tools=4,
                          imported_toolkit=str(common.ROOT), synthetic_vectors=True,
                          paid_requests=0, version=m['version'])))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'restore', 'verify'])
    p.add_argument('--tool-root', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--archive', type=Path)
    p.add_argument('--destination', type=Path)
    p.add_argument('--expected', type=Path)
    args = p.parse_args()
    # Credentials never needed for embedding. Loopback clients must not use a proxy.
    os.environ['VOYAGE_API_KEY'] = ''
    for name in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        os.environ.pop(name, None)
    os.environ['NO_PROXY'] = '127.0.0.1,localhost'
    sys.path.insert(0, str(args.tool_root.resolve()))
    if args.action == 'prepare':
        prepare(args.tool_root.resolve(), args.output.resolve())
    elif args.action == 'restore':
        restore(args.archive.resolve(), args.destination.resolve(), args.expected.resolve())
    else:
        verify(args.tool_root.resolve(), args.expected.resolve())
