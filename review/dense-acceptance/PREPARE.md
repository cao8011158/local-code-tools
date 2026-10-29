# Dense attachment and bounded acceptance preparation

Prepared offline on 2026-10-29. No API request, new graph build, source reparse, publication, or formal review occurred in this preparation. The frozen runtime is `/tmp/lct-b3-isolated-v2-20261029`, version `20261029T111748-7a235bf36f`: 5,957 nodes, 42,492 edges, 4,070 planned vector chunks, `dense_ready=false`. Its source fingerprint is `12fe107f9c97d29261ea06cfd60c5c0e72e0a6a93aac9abb3af63c156de052fd`; canonical graph SHA256 is `1b220e9c80aca289ba2a7c86ffcf09d0a2cae9874310c96cd4bb2ebd2951e13b`. This is the baseline for `verify.py`. The configured embedding ceiling remains USD 2, below the user's USD 3 total authorization. Existing estimates are not final invoices.

## Supported and missing paths

`lct/storage.py:181-345` has only `build()`. It always calls `inventory()`, `extract()`, and `Graph(...).build()` before `Embeddings.get_many()` and HNSW partition construction. Calling `build()` again would reparse the frozen graph and is outside this continuation. Merely filling `vectors.sqlite`, changing `manifest.json`, or patching `Graph.build` is not an accepted published dense feature. The existing index reader already handles partitioned approximate/exact cosine, repository/level/test filtering (`lct/query.py:115-175`) and BM25+dense reciprocal-rank fusion (`lct/query.py:233-345`). `lct/management.py:119-224` validates and relocates a complete published archive; it does not attach vectors.

The added production operation is `attach_dense(c, expected_version, offline=False, expected_program_hash=None)`, exposed as `attach-dense --version VERSION --expected-program-hash HASH --offline`. It acquires `update.lock` and fences on the expected current version; it loads the lexical predecessor with `manifest(..., compatible=False)` because editing executable code changes `program_hash`. A different predecessor program hash must be explicitly supplied and matched, while schema/config/model/HNSW and artifact validation remain mandatory. It reads `nodes ORDER BY node_id` and `files` from the immutable predecessor catalog, matching the frozen-catalog cache preflight, reconstructs `embedding_texts(nodes, files)` from captured source and asserts the planned chunk count. It does not invoke `inventory`, `extract`, or `Graph`, and does not read live project source.

After cached/authorized `Embeddings.get_many` finishes, create a **new** candidate version; copy the catalog byte-for-byte, build normalized `.npy`, `.usearch`, `.json` partitions with the existing algorithm and exact node mapping, and retain predecessor graph/source metadata and node/edge counts. Set actual `vector_chunks`, `dense_ready=true`, `embedding_run`, `incremental.previous`, new `program_hash`, and newly hashed artifact membership/sizes. Verify the copied catalog checksum equals the predecessor checksum, validate all artifacts, then atomically activate only if the expected pointer still matches. Failure must leave the lexical version current and cached vectors durable. Preserve the predecessor's source fingerprint and captured file metadata; state clearly that source freshness is the predecessor's last check, not a fresh scan. `activate()`/pruning should follow the existing publication protocol. The old version may become incompatible for interactive queries after code changes; backup/restore only require the newly published current version to be compatible.

Order is a real detail: `embedding_texts` in `lct/extract.py:214-266` uses child traversal for module/class text. The cache preflight and attachment both read `nodes ORDER BY node_id`; this explicit agreement is required for cache reuse. The stored `files.text` supplies exact function chunks, so no source parse is necessary. The vector cache (`lct/embedding.py:15-19, 173-202`) keys model/dimension/dtype/input type/text; it cannot stand in for a versioned index.

## Acceptance after production attachment

`verify.py` is a stand-alone offline observation harness for a **real published** dense version. It fails closed on a lexical-only manifest; verifies all manifest artifacts, the baseline graph/source/node/edge identity, and presence of the eleven actual query vectors in the cache. Its only Python override denies `Embeddings.call` so no uncached query can reach the provider; it fabricates neither vector nor search result. It compares production HNSW to production exact cosine at k=10 and 50 for each case/level, with mean recall >=0.95 and minimum >=0.80, then runs actual BM25/dense/RRF queries and checks scope and fusion rank provenance. It records gold-label ranks from `review/evaluation-expected.json`; that file says labels are limited manual expectations, not exhaustive truth. In particular, the `RE` case has ambiguous matching nodes and `mixed` has no gold label; review actual ranks rather than declaring all relevance perfect by threshold alone.

Example invocation after the root publishes a new dense version (the root supplies toolkit/config/output paths):

```bash
PYTHON=/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python
$PYTHON review/dense-acceptance/verify.py \
  --toolkit /tmp/lct-b3-isolated-v2-20261029 \
  --config /tmp/lct-b3-isolated-v2-20261029/config.json \
  --expected review/evaluation-expected.json \
  --output review/dense-acceptance/original-observations.json \
  --baseline-version 20261029T111748-7a235bf36f \
  --baseline-nodes 5957 --baseline-edges 42492 \
  --baseline-graph-sha256 1b220e9c80aca289ba2a7c86ffcf09d0a2cae9874310c96cd4bb2ebd2951e13b \
  --baseline-source-fingerprint 12fe107f9c97d29261ea06cfd60c5c0e72e0a6a93aac9abb3af63c156de052fd
```

Then use the production `backup(c)` and actual downloadable archive. Restore that archive into a new destination using production `restore(c, archive, destination)`, run the same `verify.py` with `--toolkit DEST --config DEST/config.json --output ... --compare review/dense-acceptance/original-observations.json`. Keep original and restored results and archive/receipt SHA256. Downloaded restore should additionally verify source retrieval and MCP/Neo4j contracts using the already bounded prior procedures; this harness focuses on dense index identity and retrieval. Never copy a local backup and call it download evidence. No full graph rebuild or broad suite is needed for this narrow gate. Formal Batch 3 review remains 2/3.
