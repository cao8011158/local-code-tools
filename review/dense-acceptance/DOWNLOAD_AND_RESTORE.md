# Full graph + vector toolkit checkpoint (2026-10-29)

The full normal product backup is182,274,492bytes. The Drive connector rejects individual files above100MiB, so this backup is preserved as two raw byte parts. They are NOT two independent ZIPs. Both were downloaded and reassembled successfully with the original SHA256:

`2e7a704c60ada3529ef9759761afd390e348adcd37271694abf4aec5c95901e3`

- Part1: https://drive.google.com/file/d/1LVfQuOpck7lx9YrbJzwDhQ6Wv0LWAvl6/view?usp=drivesdk
- Part2: https://drive.google.com/file/d/1rQrtU3bZFkh3Eb9P8dPho4BJU4RLYPKY/view?usp=drivesdk

Download both using their original names. Save parts.json and reassemble.py alongside them, then run `python reassemble.py parts.json`. Use the product's supported restore operation after the hash check. The archive contains config, fixed toolkit/lock, authoritative SQLite graph and source, BM25, current dense/HNSW partitions, cached Voyage vectors, budget ledger and retained lexical predecessor. It excludes credentials and physical Neo4j files; the Neo4j projection is rebuilt from the captured graph without source parsing.

Dense version20261029T122833-1278b3bc4b; executable hash00571c228a05d6ac6ec3cb8dd9fc8e55860de3f85bc81b8b47908a5065417c58. Code commit9da6e12288cdb32c4e0fc21a2e61185cf1a236b9. Sources remain the three frozen revisions documented in ../business-resume/SOURCE_RECOVERY.md. Dense cache4,068 document inputs/11 query inputs;4,070 partition chunks. Provider modelvoyage-code-4/dimension1024, no fabricated vectors.

This is a preservation/retrieval checkpoint, NOT a final merged release. Actual stdio MCP index_status timed out with a61MB status payload; its narrow repair requires human approval under the review limit. Query relevance has misses described in original-observations.json; UNKNOWN call analysis remains. Existing package dependencies must be installed in a new environment. No API key is bundled. Cached test queries work offline; unseen dense queries need an authorized key.
