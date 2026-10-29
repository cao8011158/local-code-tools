# Neo4j HTTP MCP（Batch 2 transport preparation）

`lct.neo4j_mcp.create_app` returns an authenticated Streamable HTTP ASGI application with four read-only tools: `graph_status`, `list_nodes`, `get_nodes`, `get_relations`. Each result contains the fixed `namespace`, `version`, `fingerprint`, and a `data` field. The scope and Neo4j database are fixed when constructing the app; no tool accepts a different scope, configuration, import path, or Cypher. At ASGI startup the application reads only the fingerprint marker of the complete imported snapshot; this verifies that the named graph exists, but does not compare its identity with an external vector or BM25 index. The full source and graph metadata remain available through `graph_status`. The application closes its owned Neo4j driver at shutdown. Reads use a worker thread; existing small-graph limits remain in force.

An embedding application must supply a production `TokenVerifier` that validates tokens against its real OAuth issuer (including signature, issuer, expiry and audience), and configure the official MCP SDK auth settings. For example, after configuring `verifier` with your OAuth provider:

```python
from mcp.server.auth.settings import AuthSettings
from lct.neo4j_mcp import create_app

app = create_app(
    uri=neo4j_uri, user=neo4j_user, password=neo4j_password,
    database="neo4j", namespace="review-a", version="published-index-version",
    token_verifier=verifier,
    auth=AuthSettings(
        issuer_url="https://your-issuer.example",
        resource_server_url="https://graph.example/mcp",
        validate_token_resource=True,
        required_scopes=["graph:read"],
    ),
    allowed_host="graph.example", allowed_origin="https://graph.example",
)
```

The SDK enforces bearer authentication, `graph:read`, and the resource audience, and serves protected-resource metadata. `allowed_host` is the exact HTTP Host header including port if used; `allowed_origin` is the exact Origin value. Wildcards are rejected; DNS rebinding protection is enabled. Do not use the synthetic local-test verifier in a deployment. Backend errors return a generic tool error so credentials and driver connection strings are not exposed to clients.

This is transport preparation, **not a deployed or connected ChatGPT integration**. Work-local execution is the intended acceptance path for this batch; public HTTPS deployment and plugin installation are not prerequisites for that path. If separately deploying this transport, the deployment needs a real OAuth issuer/verifier and resource URL, HTTPS endpoint and domain configuration, constrained Neo4j credentials, installation in the target ChatGPT workspace, and a remote connection acceptance run. No public endpoint or provider credentials are included here. The local acceptance test sets `LCT_TEST_NEO4J_URI` (optionally `LCT_TEST_NEO4J_USER`, `LCT_TEST_NEO4J_PASSWORD`, `LCT_TEST_NEO4J_DATABASE`) and runs `pytest -q tests/test_neo4j_http_mcp.py`; without the service URI, its real-service case skips.

See [portable restore](PORTABLE_RESTORE.md) for the Work-local backup and relocation contract. The Drive-to-clean-path restore acceptance gate remains pending. Small-graph validation does not establish full-graph or scale behavior.
