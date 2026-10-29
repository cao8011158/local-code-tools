# Batch3 dense completion checkpoint — human decision required

Production commit9da6e12288cdb32c4e0fc21a2e61185cf1a236b9; work branchfeat/full-business-graph-indexes. No merge. Final review3/3 requires changes because B3-005 blocks actual stdio MCP status. Root stopped automatic production fixes; successful artifacts and unrelated acceptance remain preserved.

## Completed

- Voyage-code-4/1024-dimensional real vectors:4,068 unique document inputs plus11 query inputs,80 successful requests,0 retries/errors. Provider-reported1,047,502 tokens; list-rate equivalentUSD0.12570024 atUSD0.12/M (https://blog.voyageai.com/2026/08/13/voyage-code-4/). Not account billing proof. Authorized ceilingUSD3; unchanged internalUSD2 ceiling stricter. Conservative reservation5,084,064 units. Credential stayed in no-echo process environment, process terminated after completion, no key in package/repository.
- Published dense20261029T122833-1278b3bc4b:4,070 chunks across6 repository/kind partitions in2.35s,all cache hits/no paid requests. Frozen graph remains5,957nodes/42,492edges; catalog hash7d260089cb4cfa45f4105509cb10283bbc2fd48504b54cebfad92ff61e2508e4 unchanged. Original source identity preserved; no parser rerun.
- Developer final4passed; fast446passed/18skipped. Independent full native Neo4j suite plus8 boundaries474passed/1skipped,108.02s. Existing optional skip and deprecation warning recorded. These are fixed-code checks, not evidence that actual status protocol succeeded.
- Actual26 HNSW/exact comparisons across11 queries:meanrecall99.538%,minimum92%. Actual BM25/dense/RRF filters and rank provenance passed. Limited manual relevance labels have misses:Q05Chinese absent from dense/RRFTop50; expandedQ05 BM25rank5/RRFrank20/denseabsent. Q30expanded dense2/RRF16. No claim that RRF always improves relevance or that labels exhaust correctness.
- Supported full product backup182,274,492bytes. Single upload rejected100MiB connector limit. Two raw parts uploaded privately, metadata size checked, actually downloaded and concatenated; completeSHA2562e7a704c60ada3529ef9759761afd390e348adcd37271694abf4aec5c95901e3 matched.
- Production restore from downloaded/reassembled archive into new directory with original data and source directories unavailable:PASS. All26 approximate/exact observations and11 query rankings exactly matched, BM25module/class/function/docs and3 captured-source checks matched. Shared installed dependencies; not clean-machine dependency installation. Originals restored afterward. No extra provider calls. See portable-acceptance.json.

## B3-005: actual stdio MCP status failure

Actual client initialized and called index_status; request timed out after60seconds, so later four tools were NOT reached in this real-data run. Earlier small-graph all-five-tool tests and previous Neo4j HTTP four-tool checks remain valid within their scopes.

Query.index_status (`lct/query.py`) inserts `graph: m["graph"]` into status. `lct/mcp_server.py:index_status` passes that complete result to the SDK. Direct local status creation took0.5656seconds; canonical status61,240,616bytes,of which graph61,238,037bytes. Without graph the status is2,570bytes. This demonstrates an unnecessarily huge status response and a real protocol timeout; no profiler was run to attribute every second among JSON/SDK/pipe/client processing.

This is distinct from fixedB3-004: that fixed Neo4jMCP startup's fingerprint read. This failure is the LCTstdio index_status tool's result body. Do not reopen the parser, vector generator or staged Neo4j importer.

Proposed narrow repair for HUMAN approval: make ordinary index_status return bounded graph summary/version/counts/limits; keep full analysis evidence in storage and expose needed details only by explicit bounded retrieval. Preserve UNKNOWN/reasons/completeness in detailed graph queries. Add response-size boundary test with a large analysis fixture and real all-five-tool acceptance on the already saved dense corpus. No new embedding request or source graph rebuild needed. Existing consumers/tests expecting full graph in status need explicit contract adjustment, not silent deletion of evidence. Third-review ceiling and previous-batch reopening require approval before implementation. No automatic merge.

## Recovery

See DOWNLOAD_AND_RESTORE.md,parts.json,reassemble.py. Archive contains authoritative SQLite graph/source,BM25,actual vectors/HNSW,tool/lock/config and budget ledger; not a physical Neo4j store. Recreate Neo4j projection from captured graph when required, without source analysis. The original complete lexical backup and partial paid-cache checkpoint remain preserved. Raw original/restored rankings are in the accompanying evidence archive; retrieval-summary.json retains labels and hashes in GitHub.
