# Batch 2 transport preparation — code review PASS; remote gate PENDING

Date: 2026-10-28. Formal review round: 1 of maximum 3.

Baseline/default branch: `3d06e10744d02fb5882d407aa1accd54dd62b848`.
Reviewed implementation: `b8185545cb7460e0117514bd8bde5117ff3c1d98` on `feat/neo4j-http-mcp-small-graph`.
All three new implementation/test/documentation files were fetched back from GitHub at that commit, Git blob hashes checked, and installed into a separate baseline review directory. No production implementation changes were required during review.

## Validation

Independent targeted run: **4 passed, 1 warning in 6.35s**. Developer evidence separately: 2 passed in 5.66s. Neo4j Community 5.26.0, Java 17, neo4j driver 5.26.0, MCP SDK 1.30.0, Python 3.12.14. Owned Neo4j used 384 MiB maximum heap/128 MiB page cache and was stopped after testing. No paid API calls, public endpoints, production data or full-suite runs.

```sh
uv sync --locked --group neo4j
# Start an isolated Neo4j 5.26 service; set LCT_TEST_NEO4J_URI,
# LCT_TEST_NEO4J_USER, LCT_TEST_NEO4J_PASSWORD, LCT_TEST_NEO4J_DATABASE.
pytest -q tests/test_neo4j_http_mcp.py tests/test_neo4j_http_review_independent.py
```

The real loopback HTTP test builds the established 17-node/30-edge fixture offline, imports it with the accepted Neo4j projection, starts uvicorn, and uses the official MCP ClientSession. It validates exactly four read-only tools, fixed namespace/version/fingerprint, module/class/function filters, node/relationship roundtrips, UNKNOWN evidence, and unchanged graph data. Missing/bad tokens, wrong resource audience, missing required scope, invalid Host and invalid Origin are rejected. Extra tool arguments cannot change the server scope. Production factory rejects absent verifier, absent required scope, and wildcard transport host configuration.

Independent additional probes use a controlled backend and test-only verifier to check expiry rejection; protected-resource discovery metadata and authentication challenge; startup failure redaction plus driver cleanup; backend tool error redaction; normal shutdown driver cleanup. These complement rather than replace the real database/HTTP test.

The one warning is the MCP SDK's deprecated `streamablehttp_client` test-client alias. It remains functional in the pinned SDK; no production warning or failure was observed. Avoided unrelated API/test refactoring during this batch.

## Acceptance still outstanding

This is an OAuth resource-server factory, not an OAuth authorization server or a deployed service. A production caller must supply a real issuer/token verifier that authenticates tokens and validates issuer, signature, expiry and audience. The SDK additionally requires `graph:read` and exact resource binding. Test credentials exist only in tests. No unauthenticated production fallback is shipped.

Batch 2 cannot be marked complete or merged until a reachable HTTPS deployment (or explicitly selected supported private tunnel), real authentication configuration, installation in the intended ChatGPT environment and actual tool calls from that environment have been verified. Local HTTP protocol success does not establish public reachability or ChatGPT tool attachment. Available tools in this review session cannot provision that hosting or install an arbitrary custom MCP server. User input is needed for hosting/authentication setup; never request secrets pasted into the conversation.

Official connection guidance consulted: https://developers.openai.com/api/docs/guides/custom-mcp-server (accessed 2026-10-28). It documents adding a Server URL or Secure MCP Tunnel as a plugin, configuring authentication, installing it and selecting it in the conversation. OAuth/No authentication are the listed connection choices; a synthetic fixed bearer token is not evidence of ChatGPT-compatible production login.

Decision: **code preparation PASS; overall Batch 2 PENDING external connection acceptance. Do not merge yet. Do not start Batch 3 full business indexing or paid embedding calls.** This is an environment/configuration dependency, not a confirmed P0/P1 finding or a failed review round. The following evidence commit adds this report and independent tests only.
